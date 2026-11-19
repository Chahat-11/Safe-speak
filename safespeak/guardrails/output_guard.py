"""Output guardrail: after_agent callback on the Coordinator.

The last thing that runs. It:
  1. falls back to a safe generic answer if no verdict/explanation exists,
  2. removes any "what to do" step that tells the user to share a secret, and,
     unless the verdict is likely_safe, any step that tells them to click the
     link, pay, or install an app (the moves a scam wants them to make),
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
from safespeak.schemas import CaseRecord, CaseStatus, Explanation, Verdict, VerdictLabel

_VERB = r"\b(share|send|give|tell|enter|forward|reply|confirm|provide|type|read out|dictate|bhejo|batao|bata do|de do)\b"
_SECRET = r"(\b(otp|m?pin|password|cvv|code|aadhaa?r|card (number|details)|account (number|details)|bank details)\b|\[otp\])"
# Verb before secret ("share the OTP") or after it, as in Hinglish ("OTP share karo").
_SHARE_SECRET = re.compile(rf"(?i){_VERB}.{{0,30}}{_SECRET}|{_SECRET}.{{0,30}}{_VERB}")
_NEGATION = re.compile(r"(?i)\b(never|don't|dont|do not|not|mat|nahi|na|avoid|without)\b")
# What a scam wants you to do. Fine for a genuine message, unsafe advice otherwise.
_RISKY_ACTION = re.compile(
    r"(?i)\b(click|open|tap|visit|follow)\b.{0,25}\b(link|url)\b"
    r"|\b(pay|transfer|deposit)\b.{0,25}\b(fee|money|amount|charges?|rs\.?|₹|inr)"
    r"|\b(install|download)\b.{0,30}\b(app|apk|anydesk|teamviewer|quick ?support|rustdesk)\b"
)
_OFFICIAL = re.compile(r"(?i)\b(official|1930|cybercrime\.gov\.in|sancharsaathi)\b")


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

    explanation = _drop_unsafe_steps(state, case.explanation, case.verdict)
    markdown, found = redact(render_markdown(case.verdict, explanation))
    if found:
        log_guardrail(state, "output", "redacted", f"Masked in output: {', '.join(sorted(set(found)))}")
    return markdown


def _drop_unsafe_steps(state, explanation: Explanation, verdict: Verdict) -> Explanation:
    genuine = verdict.label == VerdictLabel.LIKELY_SAFE
    safe = [step for step in explanation.what_to_do if not is_unsafe_step(step, genuine)]
    if len(safe) == len(explanation.what_to_do):
        return explanation
    dropped = len(explanation.what_to_do) - len(safe)
    log_guardrail(state, "output", "replaced", f"Removed {dropped} unsafe step(s) from the advice.")
    safe = safe or ["Do not reply, click links, or share any codes."]
    return explanation.model_copy(update={"what_to_do": safe})


def is_unsafe_step(step: str, genuine: bool = False) -> bool:
    """True for e.g. 'Share the OTP with the agent', but not 'Never share your OTP'.

    Unless the message is judged genuine, also true for 'Click the link to
    claim', 'Pay the Rs 99 fee' or 'Install AnyDesk', but not for steps that
    point to official channels ('Visit the official website', 'Call 1930').
    """
    if _NEGATION.search(step):
        return False
    if _SHARE_SECRET.search(step):
        return True
    return not genuine and bool(_RISKY_ACTION.search(step)) and not _OFFICIAL.search(step)
