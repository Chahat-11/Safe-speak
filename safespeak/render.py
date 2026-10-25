"""Turn the typed Verdict + Explanation into the Markdown the user reads.

Kept separate from the agents so the final wording/layout is plain code you
can change without touching any prompt.
"""

from safespeak.schemas import Explanation, Verdict, VerdictLabel

LOW_CONFIDENCE = 0.5

_TITLES = {
    VerdictLabel.SCAM: "⚠️ This is a scam",
    VerdictLabel.SUSPICIOUS: "⚠️ This looks suspicious",
    VerdictLabel.LIKELY_SAFE: "✅ This looks safe",
    VerdictLabel.UNCERTAIN: "❔ SafeSpeak is not sure",
}

_LOW_CONFIDENCE_NOTE = (
    "_SafeSpeak is not confident about this one. If in doubt, contact the "
    "organisation using a number or website you already trust._"
)

FALLBACK_MARKDOWN = (
    "## ❔ SafeSpeak could not finish the analysis\n\n"
    "Treat this message with caution:\n\n"
    "1. Do not click links or call numbers in the message.\n"
    "2. Never share an OTP, PIN or password.\n"
    "3. Contact the organisation through its official app or website."
)


def render_markdown(verdict: Verdict, explanation: Explanation) -> str:
    lines = [
        f"## {_TITLES[verdict.label]}",
        "",
        explanation.headline,
        "",
        f"**Confidence:** {verdict.confidence:.0%}",
    ]
    if verdict.confidence < LOW_CONFIDENCE:
        lines += ["", _LOW_CONFIDENCE_NOTE]
    lines += ["", "### Why", *[f"- {reason}" for reason in explanation.why]]
    lines += ["", "### What to do", *[f"{i}. {step}" for i, step in enumerate(explanation.what_to_do, 1)]]
    return "\n".join(lines)
