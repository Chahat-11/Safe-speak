"""Structured trace logging: one JSON object per line in logs/trace.jsonl.

Every agent, model and tool call produces one record with:
  kind, name, invocation_id, case_id, duration_ms, tokens, input, output.
Callbacks here only OBSERVE: they never change state or return content.

Durations are inclusive: the Coordinator's time contains its sub-agents.
Only redacted text ever reaches these callbacks (raw input is masked first).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

from safespeak import config
from safespeak.blackboard import CASE_KEY
from safespeak.schemas import AgentMetrics, RunMetrics

_MAX_TEXT = 4000  # truncate long prompts/responses in the log


class Tracer:
    def __init__(self, path: Path):
        self.path = path
        self._starts: dict[tuple, float] = {}
        self._case_before: dict[tuple, dict] = {}
        self._prompts: dict[tuple, str] = {}
        self._metrics: dict[str, dict[str, AgentMetrics]] = {}
        self.listeners: list[Callable[[dict], None]] = []  # live subscribers (the UI)

    # ---- live events -----------------------------------------------------

    def _emit(self, event: str, ctx: CallbackContext, *, name: str | None = None, **fields: Any) -> None:
        """Tell live subscribers what just happened. The case is already masked."""
        if not self.listeners:
            return
        record = {"event": event, "name": name or ctx.agent_name, "t": round(time.time() * 1000),
                  "case": ctx.state.get(CASE_KEY), **fields}
        for listener in self.listeners:
            listener(record)

    def guarded(self, guard: Callable) -> Callable:
        """Wrap a before_agent guardrail so a skipped agent is visible and timed out."""

        def callback(callback_context: CallbackContext):
            result = guard(callback_context)
            if result is not None:
                self._forget("agent", callback_context)
                self._emit("agent_skipped", callback_context, guard=guard.__name__)
            return result

        return callback

    def guarded_model(self, guard: Callable) -> Callable:
        """Same for a before_model guardrail that answers instead of the LLM."""

        def callback(callback_context: CallbackContext, llm_request: LlmRequest):
            result = guard(callback_context, llm_request)
            if result is not None:
                self._forget("model", callback_context)
                self._emit("model_skipped", callback_context, guard=guard.__name__)
            return result

        return callback

    def _forget(self, kind: str, ctx: CallbackContext) -> None:
        key = (kind, ctx.invocation_id, ctx.agent_name)
        self._starts.pop(key, None)
        self._case_before.pop(key, None)
        self._prompts.pop(key, None)

    # ---- agent callbacks -------------------------------------------------

    def before_agent(self, callback_context: CallbackContext) -> None:
        key = ("agent", callback_context.invocation_id, callback_context.agent_name)
        self._starts[key] = time.perf_counter()
        self._case_before[key] = dict(callback_context.state.get(CASE_KEY) or {})
        self._emit("agent_start", callback_context)

    def after_agent(self, callback_context: CallbackContext) -> None:
        key = ("agent", callback_context.invocation_id, callback_context.agent_name)
        duration = self._elapsed_ms(key)
        before = self._case_before.pop(key, {})
        after = callback_context.state.get(CASE_KEY) or {}
        self._agent_metrics(callback_context).calls += 1
        self._agent_metrics(callback_context).duration_ms += duration
        self.write(
            kind="agent",
            ctx=callback_context,
            duration_ms=duration,
            input={"status": before.get("status")},
            output=_changed_sections(before, after),
        )
        self._emit("agent_end", callback_context, duration_ms=duration, wrote=sorted(_changed_sections(before, after)))

    # ---- model callbacks -------------------------------------------------

    def before_model(self, callback_context: CallbackContext, llm_request: LlmRequest) -> None:
        key = ("model", callback_context.invocation_id, callback_context.agent_name)
        self._starts[key] = time.perf_counter()
        self._prompts[key] = _truncate(str(llm_request.config.system_instruction))
        self._emit("model_start", callback_context)

    def after_model(self, callback_context: CallbackContext, llm_response: LlmResponse) -> None:
        key = ("model", callback_context.invocation_id, callback_context.agent_name)
        duration = self._elapsed_ms(key)
        prompt_tokens, completion_tokens = _tokens(llm_response)
        prompt = self._prompts.get(key, "")
        metrics = self._agent_metrics(callback_context)
        metrics.model_calls += 1
        metrics.prompt_tokens += prompt_tokens
        metrics.completion_tokens += completion_tokens
        self.write(
            kind="model",
            ctx=callback_context,
            duration_ms=duration,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            input=self._prompts.pop(key, ""),
            output=_truncate(_response_text(llm_response)),
            error=llm_response.error_message,
        )
        self._emit("model_end", callback_context, duration_ms=duration, prompt_tokens=prompt_tokens,
                   completion_tokens=completion_tokens, prompt=prompt, reply=_truncate(_response_text(llm_response)))

    # ---- tool callbacks (used once MCP tools are attached) ---------------

    def before_tool(self, tool: Any, args: dict, tool_context: CallbackContext) -> None:
        self._starts[("tool", tool_context.invocation_id, tool.name)] = time.perf_counter()
        self._emit("tool_start", tool_context, tool=tool.name, args=args)

    def after_tool(self, tool: Any, args: dict, tool_context: CallbackContext, tool_response: Any) -> None:
        duration = self._elapsed_ms(("tool", tool_context.invocation_id, tool.name))
        self.write(kind="tool", ctx=tool_context, name=tool.name, duration_ms=duration,
                   input=args, output=tool_response)
        finding = tool_response.get("structuredContent") if isinstance(tool_response, dict) else None
        self._emit("tool_end", tool_context, tool=tool.name, args=args, duration_ms=duration, finding=finding)

    # ---- run summary -----------------------------------------------------

    def finish_run(self, invocation_id: str, case_id: str | None) -> RunMetrics:
        """Called once per message by the app: log and return RunMetrics."""
        agents = list(self._metrics.pop(invocation_id, {}).values())
        metrics = RunMetrics(invocation_id=invocation_id, case_id=case_id, agents=agents)
        self._append({"kind": "run", "invocation_id": invocation_id, "case_id": case_id,
                      "total_tokens": metrics.total_tokens, "metrics": metrics.model_dump()})
        return metrics

    # ---- helpers ---------------------------------------------------------

    def write(self, *, kind: str, ctx: CallbackContext, name: str | None = None, **fields: Any) -> None:
        case = ctx.state.get(CASE_KEY) or {}
        record = {"kind": kind, "name": name or ctx.agent_name,
                  "invocation_id": ctx.invocation_id, "case_id": case.get("case_id"), **fields}
        self._append(record)

    def _append(self, record: dict) -> None:
        record = {"ts": datetime.now(timezone.utc).isoformat(), **record}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")

    def _elapsed_ms(self, key: tuple) -> float:
        start = self._starts.pop(key, None)
        return round((time.perf_counter() - start) * 1000, 1) if start else 0.0

    def _agent_metrics(self, ctx: CallbackContext) -> AgentMetrics:
        per_run = self._metrics.setdefault(ctx.invocation_id, {})
        return per_run.setdefault(ctx.agent_name, AgentMetrics(agent=ctx.agent_name))


def _changed_sections(before: dict, after: dict) -> dict:
    """What this agent wrote to the blackboard (sections whose value changed)."""
    return {k: v for k, v in after.items() if before.get(k) != v}


def _tokens(response: LlmResponse) -> tuple[int, int]:
    usage = response.usage_metadata
    if usage is None:
        return 0, 0
    return usage.prompt_token_count or 0, usage.candidates_token_count or 0


def _response_text(response: LlmResponse) -> str:
    if not response.content or not response.content.parts:
        return ""
    return "".join(p.text or "" for p in response.content.parts if not p.thought)


def _truncate(text: str) -> str:
    return text if len(text) <= _MAX_TEXT else text[:_MAX_TEXT] + "...[truncated]"


# One tracer for the process; agents register its bound methods as callbacks.
tracer = Tracer(config.LOG_PATH)
