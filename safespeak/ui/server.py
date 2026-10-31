"""The monitor's small web server. Local only: binds to 127.0.0.1.

  POST /api/analyse  {"text", "architecture"} -> Server-Sent Events, live
  GET  /api/replay                            -> the recorded sample, same format
  GET  /api/health                            -> is Ollama up, which model

It only subscribes to tracer events, so the UI cannot change how agents behave.
The raw message is never sent back: every event carries the masked case.
One run at a time, because the local model handles one request at a time.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from safespeak import app as pipeline
from safespeak import config
from safespeak.observability.tracer import tracer

STATIC = Path(__file__).parent / "static"
SAMPLE = Path(__file__).parent / "sample_run.jsonl"
REPLAY_MAX_PAUSE = 0.9  # seconds; a recorded 25 s run replays in a few seconds

_run_lock = asyncio.Lock()


def sse(record: dict) -> str:
    return f"data: {json.dumps(record, default=str, ensure_ascii=False)}\n\n"


def done_event(result: pipeline.AnalysisResult) -> dict:
    return {"event": "done", "markdown": result.markdown, "metrics": result.metrics.model_dump(),
            "total_tokens": result.metrics.total_tokens,
            "case": result.case.model_dump(mode="json") if result.case else None}


async def stream_run(text: str, architecture: str):
    """Yield each tracer event as it happens, then the final result."""
    queue: asyncio.Queue = asyncio.Queue()
    tracer.listeners.append(queue.put_nowait)

    async def run() -> None:
        try:
            queue.put_nowait(done_event(await pipeline.analyse(text, architecture=architecture)))
        except Exception as err:
            queue.put_nowait({"event": "error", "kind": type(err).__name__, "message": str(err).splitlines()[0][:300]})

    task = asyncio.create_task(run())
    try:
        while True:
            record = await queue.get()
            yield sse(record)
            if record["event"] in ("done", "error"):
                return
    finally:
        tracer.listeners.remove(queue.put_nowait)
        task.cancel()
        if _run_lock.locked():
            _run_lock.release()


async def analyse_endpoint(request: Request):
    body = await request.json()
    text, architecture = body.get("text", ""), body.get("architecture", "hierarchical")
    if architecture not in pipeline.ARCHITECTURES:
        return JSONResponse({"error": "Unknown architecture."}, status_code=400)
    if _run_lock.locked():
        return JSONResponse({"error": "Another analysis is still running."}, status_code=409)
    await _run_lock.acquire()
    return StreamingResponse(stream_run(text, architecture), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store"})


async def replay_events():
    """The recorded run with long waits shortened, keeping the order and the feel."""
    previous = None
    for line in SAMPLE.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        t = record.get("t")
        if previous is not None and t is not None:
            await asyncio.sleep(min((t - previous) / 1000, REPLAY_MAX_PAUSE))
        previous = t if t is not None else previous
        yield sse(record)


async def replay_endpoint(_: Request):
    if not SAMPLE.exists():
        return JSONResponse({"error": "No recorded sample."}, status_code=404)
    return StreamingResponse(replay_events(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})


async def health_endpoint(_: Request):
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            ollama = (await client.get(f"{config.OLLAMA_API_BASE}/api/version")).status_code == 200
    except httpx.HTTPError:
        ollama = False
    return JSONResponse({"ollama": ollama, "model": config.MODEL, "architectures": list(pipeline.ARCHITECTURES),
                         "sample": SAMPLE.exists()})


app = Starlette(routes=[
    Route("/api/analyse", analyse_endpoint, methods=["POST"]),
    Route("/api/replay", replay_endpoint),
    Route("/api/health", health_endpoint),
    Mount("/", StaticFiles(directory=STATIC, html=True)),
])
