"""Verdict check: after_agent callback on the Reasoner.

The Reasoner's prompt gives each label a confidence band, but the LLM does
not always respect it, and nothing stopped it calling a message "likely_safe"
while a blocklist said the link was malicious. Two rules, in code:

  1. Strong evidence floor: if a verifier result is "malicious" or a scam
     pattern with weight >= STRONG_PATTERN matched, the label cannot be
     likely_safe; it is raised to suspicious. Telling someone a scam is safe
     is the worst mistake this system can make.
  2. Confidence is clamped into its label's band, so "90% confident" means
     the same thing on every run.

Each change is logged as a GuardrailEvent; the Reasoner's reasons are kept.
"""

from google.adk.agents.callback_context import CallbackContext

from safespeak.blackboard import log_guardrail, post, read_case
from safespeak.schemas import CaseRecord, CheckResult, Verdict, VerdictLabel

STRONG_PATTERN = 0.8
# Must match the bands written in the Reasoner's prompt (agents/reasoner.py).
CONFIDENCE_BANDS = {
    VerdictLabel.SCAM: (0.75, 0.95),
    VerdictLabel.SUSPICIOUS: (0.55, 0.75),
    VerdictLabel.LIKELY_SAFE: (0.6, 0.9),
    VerdictLabel.UNCERTAIN: (0.4, 0.6),
}


def check_verdict(callback_context: CallbackContext) -> None:
    state = callback_context.state
    case = read_case(state)
    if case.verdict is None:
        return
    checked, changes = enforce(case.verdict, case)
    if changes:
        post(state, "verdict", checked)
        log_guardrail(state, "agent", "replaced", "Verdict corrected: " + "; ".join(changes))


def enforce(verdict: Verdict, case: CaseRecord) -> tuple[Verdict, list[str]]:
    """Pure function (easy to test): (corrected verdict, what changed)."""
    changes = []
    label = verdict.label
    strong = strong_evidence(case)
    if label == VerdictLabel.LIKELY_SAFE and strong:
        label = VerdictLabel.SUSPICIOUS
        changes.append(f"likely_safe -> suspicious because of {strong}")
    low, high = CONFIDENCE_BANDS[label]
    confidence = min(max(verdict.confidence, low), high)
    if confidence != verdict.confidence:
        changes.append(f"confidence {verdict.confidence:.2f} -> {confidence:.2f} (band for {label.value})")
    return verdict.model_copy(update={"label": label, "confidence": confidence}), changes


def strong_evidence(case: CaseRecord) -> str | None:
    """Name of the first strong scam sign on the blackboard, or None."""
    for finding in case.verifier_findings:
        if finding.result == CheckResult.MALICIOUS:
            return f"a blocklisted domain ({finding.indicator})"
    for match in case.pattern_matches:
        if match.weight >= STRONG_PATTERN:
            return f"the '{match.pattern_id}' scam pattern"
    return None
