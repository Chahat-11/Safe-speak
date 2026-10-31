"""Critique grounding: after_agent callback on the Critic.

A small local model makes an unreliable judge: qwen2.5:3b rejected every
explanation on a dev sample, e.g. calling "not a scam" a contradiction of
"likely_safe". So a rewrite is triggered only by problems CODE can confirm:

  - the headline contradicts the verdict label
    (says "safe" for a scam, "scam" for likely_safe, or is certain when the
    verdict is "uncertain")

The final CriticReview = code's verdict. If the code finds a problem, the
Critic's own issues are kept alongside it (they help the rewrite). If the
Critic objected but the code found nothing, the review is approved and the
Critic's objections are logged as a GuardrailEvent, so nothing is hidden.
(Wrong script is rejected earlier by language_check; unsafe advice is
removed by the output guardrail.)
"""

import re

from google.adk.agents.callback_context import CallbackContext

from safespeak.blackboard import log_guardrail, post, read_case
from safespeak.schemas import CriticReview, Explanation, Verdict, VerdictLabel

_SAYS_SAFE = re.compile(
    r"(?i)\bnot (?:a |an )?(?:scam|fraud|fake|phishing)\b|\bisn'?t (?:a |an )?(?:scam|fraud)\b"
    r"|\bno (?:signs? of )?(?:scam|fraud)\b|\bscam nahi\b"
    r"|\b(?:is|looks|seems|appears)(?: to be)? (?:safe|genuine|legitimate|real|official)\b"
)
_SAYS_SCAM = re.compile(r"(?i)\b(?:scam|fraud|fake|phishing|dhokha)\b")
_HEDGE = re.compile(r"(?i)\b(?:may|might|could|possibly|not sure|unclear|careful|caution|suspicious)\b")


def headline_issue(verdict: Verdict, headline: str) -> str | None:
    """The one contradiction a plain reader would notice first."""
    says_safe = bool(_SAYS_SAFE.search(headline))
    says_scam = bool(_SAYS_SCAM.search(headline)) and not says_safe
    label = verdict.label
    if label in (VerdictLabel.SCAM, VerdictLabel.SUSPICIOUS) and says_safe:
        return f"Headline says the message is safe, but the verdict is {label.value}."
    if label == VerdictLabel.LIKELY_SAFE and says_scam:
        return "Headline calls the message a scam, but the verdict is likely_safe."
    if label == VerdictLabel.UNCERTAIN and (says_scam or says_safe) and not _HEDGE.search(headline):
        return "Headline sounds certain, but the verdict is uncertain; say it may or may not be a scam."
    return None


def explanation_issues(verdict: Verdict, explanation: Explanation) -> list[str]:
    issue = headline_issue(verdict, explanation.headline)
    return [issue] if issue else []


def ground_critique(callback_context: CallbackContext) -> None:
    state = callback_context.state
    case = read_case(state)
    if case.critique is None or case.verdict is None or case.explanation is None:
        return
    confirmed = explanation_issues(case.verdict, case.explanation)
    if confirmed:
        llm_issues = [] if case.critique.approved else case.critique.issues
        post(state, "critique", CriticReview(approved=False, issues=[*confirmed, *llm_issues]))
    elif not case.critique.approved:
        post(state, "critique", CriticReview(approved=True, issues=[]))
        log_guardrail(state, "agent", "replaced", "Critic objections not confirmed by checks: " + "; ".join(case.critique.issues)[:300])
