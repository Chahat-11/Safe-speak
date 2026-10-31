"""Critique grounding: after_agent callback on the Critic.

"The LLM Critic proposes, code confirms."

A small local model is an unreliable judge on its own: qwen2.5:3b listed
checks that PASSED as issues ("does not contradict the verdict") and so never
approved anything. But it does spot real problems, e.g. an explanation that
claims "they included a link" when the message has none.

So the Critic tags each issue with the check that failed, and code verifies
the tag before it can trigger a rewrite:

  [contradiction] -> headline_issue: headline contradicts the verdict label
  [unsupported]   -> unsupported_claims: a "why" reason claims a link or a
                     phone number that the message does not contain
                     (negated reasons like "no links" are skipped)

Code also runs both checks itself, so it catches what the Critic missed.
Final CriticReview: rejected only if a check confirms a problem; its issues
are the code's finding plus the Critic's wording for that check. Unconfirmed
or untagged objections are approved and logged as a GuardrailEvent.
(Wrong script is rejected earlier by language_check; unsafe advice is
removed by the output guardrail.)
"""

import re

from google.adk.agents.callback_context import CallbackContext

from safespeak.agents.pattern_catalogue import LINK
from safespeak.blackboard import log_guardrail, post, read_case
from safespeak.schemas import CaseRecord, CriticReview, Verdict, VerdictLabel

_SAYS_SAFE = re.compile(
    r"(?i)\bnot (?:a |an )?(?:scam|fraud|fake|phishing)\b|\bisn'?t (?:a |an )?(?:scam|fraud)\b"
    r"|\bno (?:signs? of )?(?:scam|fraud)\b|\bscam nahi\b"
    r"|\b(?:is|looks|seems|appears)(?: to be)? (?:safe|genuine|legitimate|real|official)\b"
)
_SAYS_SCAM = re.compile(r"(?i)\b(?:scam|fraud|fake|phishing|dhokha)\b")
_HEDGE = re.compile(r"(?i)\b(?:may|might|could|possibly|not sure|unclear|careful|caution|suspicious)\b")

_MENTIONS_LINK = re.compile(r"(?i)\blinks?\b|\burls?\b|\bwebsite\b|\bclick\w*")
_MENTIONS_NUMBER = re.compile(r"(?i)\b(?:phone|mobile|contact|specific|their|a) number\b|\bnumber (?:to|they)\b")
# "It does not contain any links" is the explanation agreeing there is no link.
_NEGATED = re.compile(r"(?i)\b(?:no|not|never|without|none|doesn'?t|isn'?t|aren'?t|don'?t|neither|nor)\b")
_HAS_NUMBER = re.compile(r"\d[\d\s-]{6,}\d|\[number\]|X{4,}", re.IGNORECASE)

_TAG = re.compile(r"^\s*\[(\w+)\]\s*(.*)$")


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


def unsupported_claims(case: CaseRecord) -> list[str]:
    """'why' reasons that describe a link or phone number the message does not have."""
    text = case.message_text
    has_link = bool(case.parsed.urls) or bool(LINK.search(text))
    has_number = bool(case.parsed.phone_numbers) or bool(_HAS_NUMBER.search(text))
    issues = []
    for reason in case.explanation.why:
        if _NEGATED.search(reason):
            continue  # precision over recall: skip "no links", "doesn't ask you to click"
        if _MENTIONS_LINK.search(reason) and not has_link:
            issues.append(f"Reason mentions a link, but the message has no link: {reason!r}")
        elif _MENTIONS_NUMBER.search(reason) and not has_number:
            issues.append(f"Reason mentions a phone number, but the message has none: {reason!r}")
    return issues


def code_checks(case: CaseRecord) -> dict[str, list[str]]:
    """Every check code can verify, keyed by the tag the Critic uses for it."""
    headline = headline_issue(case.verdict, case.explanation.headline)
    return {"contradiction": [headline] if headline else [], "unsupported": unsupported_claims(case)}


def ground_critique(callback_context: CallbackContext) -> None:
    state = callback_context.state
    case = read_case(state)
    if case.critique is None or case.verdict is None or case.explanation is None:
        return
    found = code_checks(case)
    llm_tagged = _tagged_issues(case.critique)
    confirmed = [
        issue
        for tag, code_issues in found.items()
        if code_issues
        for issue in [*code_issues, *llm_tagged.get(tag, [])]
    ]
    unconfirmed = [i for tag, items in llm_tagged.items() if not found.get(tag) for i in items]
    unconfirmed += llm_tagged.get("", [])

    post(state, "critique", CriticReview(approved=not confirmed, issues=confirmed))
    if unconfirmed:
        log_guardrail(state, "agent", "replaced", "Critic issues not confirmed by checks: " + "; ".join(unconfirmed)[:300])


def _tagged_issues(critique: CriticReview) -> dict[str, list[str]]:
    """{"unsupported": ["..."], ...}; untagged issues go under "" (cannot be verified)."""
    if critique.approved:
        return {}
    tagged: dict[str, list[str]] = {}
    for issue in critique.issues:
        match = _TAG.match(issue)
        tag, text = (match.group(1).lower(), match.group(2)) if match else ("", issue)
        tagged.setdefault(tag, []).append(text)
    return tagged
