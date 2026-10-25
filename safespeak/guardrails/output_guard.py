"""Output guardrail: after_agent callback on the Coordinator.

The last thing that runs. It:
  1. falls back to a safe generic answer if no verdict/explanation exists,
  2. removes any "what to do" step that tells the user to share a secret,
  3. renders Markdown and re-redacts it so no secret can leak out,
  4. closes the case.
Its returned Content is the final reply of the whole run.
"""

import re

from google.adk.agents.callback_context import CallbackContext
from google.genai import types

from safespeak.blackboard import has_case, log_guardrail, post, read_case
from safespeak.guardrails.redaction import redact
from safespeak.render import FALLBACK_MARKDOWN, render_markdown
from safespeak.schemas import CaseRecord, CaseStatus, Explanation

_VERB = r"\b(share|send|give|tell|enter|bhejo|batao|bata do)\b"
_SECRET = r"\b(otp|pin|password|cvv)\b"
# Verb before secret ("share the OTP") or after it, as in Hinglish ("OTP share karo").
_SHARE_SECRET = re.compile(rf"(?i){_VERB}.{{0,30}}{_SECRET}|{_SECRET}.{{0,30}}{_VERB}")
_NEGATION = re.compile(r"(?i)\b(never|don't|dont|do not|not|mat|nahi|na)\b")


def output_guardrail(callback_context: CallbackContext) -> types.Content | None:
    state = callback_context.state
    if not has_case(state):
        return None
    markdown = _safe_markdown(state, read_case(state))
    post(state, "status", CaseStatus.CLOSED)
    return types.Content(role="model", parts=[types.Part(text=markdown)])


def _safe_markdown(state, case: CaseRecord) -> str:
    if case.verdict is None or case.explanation is None:
        log_guardrail(state, "output", "replaced", "No verdict/explanation; used safe fallback.")
        return FALLBACK_MARKDOWN

    explanation = _drop_unsafe_steps(state, case.explanation)
    markdown, found = redact(render_markdown(case.verdict, explanation))
    if found:
        log_guardrail(state, "output", "redacted", f"Masked in output: {', '.join(sorted(set(found)))}")
    return markdown


def _drop_unsafe_steps(state, explanation: Explanation) -> Explanation:
    safe = [step for step in explanation.what_to_do if not is_unsafe_step(step)]
    if len(safe) == len(explanation.what_to_do):
        return explanation
    log_guardrail(state, "output", "replaced", "Removed advice to share a secret.")
    safe = safe or ["Do not reply, click links, or share any codes."]
    return explanation.model_copy(update={"what_to_do": safe})


def is_unsafe_step(step: str) -> bool:
    """True for e.g. 'Share the OTP with the agent', but not 'Never share your OTP'."""
    return bool(_SHARE_SECRET.search(step)) and not _NEGATION.search(step)
