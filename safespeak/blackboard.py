"""The blackboard: one CaseRecord stored in ADK session state.

Agents never talk to each other. They only:
  - read the case   -> read_case(state)
  - write a section -> post(state, "verdict", Verdict(...))

`state` is whatever ADK hands you: `callback_context.state`,
`tool_context.state`, or `ctx.session.state`. All are dict-like.

Why the whole record is re-assigned on every write: ADK records a state
change only when a key is *set*. Mutating a nested dict in place would be
invisible to the session service, so it would not be persisted or traced.
"""

from __future__ import annotations

from typing import Any, MutableMapping

from pydantic import BaseModel

from safespeak.schemas import CaseRecord, CaseStatus, GuardrailEvent

CASE_KEY = "case"

# Identity fields are set once in open_case() and never rewritten.
_READ_ONLY = {"case_id", "created_at", "message_text"}

State = MutableMapping[str, Any]


class BlackboardError(RuntimeError):
    """Raised when the case is missing or a write is invalid."""


def open_case(state: State, message_text: str) -> CaseRecord:
    """Create a fresh case for this message and store it."""
    case = CaseRecord(message_text=message_text)
    write_case(state, case)
    return case


def has_case(state: State) -> bool:
    return state.get(CASE_KEY) is not None


def read_case(state: State) -> CaseRecord:
    """Load and validate the current case."""
    raw = state.get(CASE_KEY)
    if raw is None:
        raise BlackboardError("No open case in session state.")
    return CaseRecord.model_validate(raw)


def write_case(state: State, case: CaseRecord) -> None:
    """Store the whole case (as JSON-safe dict, which ADK state requires)."""
    state[CASE_KEY] = case.model_dump(mode="json")


def post(state: State, section: str, value: Any, status: CaseStatus | None = None) -> CaseRecord:
    """Write one section of the case, validated, and optionally advance status.

    Re-validating the whole CaseRecord means a wrong type (e.g. an
    Explanation posted into "verdict") raises instead of being stored.
    """
    if section not in CaseRecord.model_fields or section in _READ_ONLY:
        raise BlackboardError(f"Not a writable case section: {section!r}")
    case = read_case(state)
    changes: dict[str, Any] = {section: _dump(value)}
    if status is not None:
        changes["status"] = status
    updated = CaseRecord.model_validate({**case.model_dump(), **changes})
    write_case(state, updated)
    return updated


def increment_loop(state: State, counter: str) -> int:
    """Bump 'reasoner_loops' or 'critic_loops' and return the new value."""
    if counter not in ("reasoner_loops", "critic_loops"):
        raise BlackboardError(f"Unknown loop counter: {counter!r}")
    case = read_case(state)
    new_value = getattr(case, counter) + 1
    post(state, counter, new_value)
    return new_value


def close_loop(state: State, loop: str) -> None:
    """Mark a loop as closed by its cap callback ("reasoner" or "critic")."""
    case = read_case(state)
    if loop not in case.capped_loops:
        post(state, "capped_loops", [*case.capped_loops, loop])


def loop_is_closed(state: State, loop: str) -> bool:
    return loop in read_case(state).capped_loops


def log_guardrail(state: State, stage: str, action: str, reason: str) -> None:
    """Append a guardrail event to the case's audit trail."""
    case = read_case(state)
    event = GuardrailEvent(stage=stage, action=action, reason=reason)
    post(state, "guardrail_events", [*case.guardrail_events, event])


def _dump(value: Any) -> Any:
    """Turn models (or lists of models) into plain dicts for re-validation."""
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, list):
        return [_dump(v) for v in value]
    return value
