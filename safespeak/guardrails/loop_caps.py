"""Loop caps: before_agent callbacks. The ONLY place loop limits are enforced.

Two loops, same shape:
  Reasoner -> Coordinator : callback on the Router   (re-routing = loop-back)
  Critic   -> Explainer   : callback on the Explainer (re-writing = loop-back)

Each callback lets the first entry through, counts every loop-back, and once
the cap is reached it records the loop as closed (case.capped_loops), logs a
GuardrailEvent and skips the agent. The Coordinator sees the closed loop on
the blackboard and moves on. Verdicts and critiques are left untouched, so the
record still shows the Reasoner wanted more evidence / the Critic objected.
"""

from google.adk.agents.callback_context import CallbackContext
from google.genai import types

from safespeak.blackboard import close_loop, increment_loop, log_guardrail, read_case
from safespeak.schemas import MAX_CRITIC_LOOPS, MAX_REASONER_LOOPS


def cap_reasoner_loops(callback_context: CallbackContext) -> types.Content | None:
    case = read_case(callback_context.state)
    wants_loop = case.verdict is not None and case.verdict.needs_more_evidence
    return _enforce(callback_context, "reasoner", "reasoner_loops", MAX_REASONER_LOOPS, wants_loop)


def cap_critic_loops(callback_context: CallbackContext) -> types.Content | None:
    case = read_case(callback_context.state)
    wants_loop = case.critique is not None and not case.critique.approved
    # The Explainer is an LlmAgent with an output_schema, and ADK validates
    # whatever a skipped agent returns against that schema. So when vetoed it
    # "returns" its last accepted draft unchanged rather than a plain message.
    last_draft = case.explanation.model_dump_json() if case.explanation else None
    return _enforce(callback_context, "critic", "critic_loops", MAX_CRITIC_LOOPS, wants_loop, last_draft)


def _enforce(
    callback_context, loop: str, counter: str, limit: int, wants_loop: bool, veto_text: str | None = None
) -> types.Content | None:
    """Shared rule: allow first entry, allow `limit` loop-backs, then veto."""
    if not wants_loop:
        return None  # first entry, not a loop-back
    state = callback_context.state
    if getattr(read_case(state), counter) < limit:
        increment_loop(state, counter)
        return None

    close_loop(state, loop)
    reason = f"{loop} loop cap ({limit}) reached; continuing with the last result."
    log_guardrail(state, "agent", "blocked", reason)
    return types.Content(role="model", parts=[types.Part(text=veto_text or reason)])
