"""Explainer: turns the Verdict into plain-language advice.

Reads:  parsed + verdict + Critic issues (as ExplainerInput)
Writes: case.explanation  (status -> EXPLAINED)
Re-entry after a Critic rejection is capped by cap_critic_loops (before_agent).
Markdown formatting is done in code (render.py), not by the model.
"""

from safespeak.agents.common import make_llm_agent
from safespeak.guardrails.loop_caps import cap_critic_loops
from safespeak.schemas import CaseRecord, CaseStatus, Explanation, ExplainerInput

PROMPT = """You are the SafeSpeak Explainer.
Explain the verdict to an ordinary person who is not technical.
- Write in the language given by parsed.language (Hinglish if 'hinglish').
- headline: one short sentence saying whether this is a scam.
- why: 2-4 reasons in everyday words, based on verdict.key_reasons.
- what_to_do: 2-4 concrete steps (e.g. do not click the link, block the
  sender, report at cybercrime.gov.in or call 1930 in India).
- If critic_issues is not empty, fix every issue listed."""


def build_input(case: CaseRecord) -> ExplainerInput:
    issues = case.critique.issues if case.critique else []
    return ExplainerInput(parsed=case.parsed, verdict=case.verdict, critic_issues=issues)


def create_explainer(model=None):
    return make_llm_agent(
        name="explainer",
        prompt=PROMPT,
        build_input=build_input,
        output_schema=Explanation,
        section="explanation",
        status=CaseStatus.EXPLAINED,
        model=model,
        guards=[cap_critic_loops],
    )
