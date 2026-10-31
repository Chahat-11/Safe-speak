"""Record one real run for the monitor's Replay button (works with Ollama closed).

  python scripts/record_ui_sample.py "synthetic message"

Use made-up messages only: the recording is committed to the repo.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from safespeak.observability.tracer import tracer  # noqa: E402
from safespeak.ui.server import SAMPLE, done_event, pipeline  # noqa: E402


async def main(text: str) -> None:
    records: list[dict] = []
    tracer.listeners.append(records.append)
    records.append(done_event(await pipeline.analyse(text)))
    SAMPLE.write_text("\n".join(json.dumps(r, default=str, ensure_ascii=False) for r in records) + "\n", encoding="utf-8")
    print(f"{len(records)} events -> {SAMPLE}")


asyncio.run(main(" ".join(sys.argv[1:])))
