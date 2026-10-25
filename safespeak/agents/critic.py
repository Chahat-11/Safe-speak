"""Critic: reviews the Explanation against the Verdict before it reaches the user.

Reads:  parsed + verdict + explanation   (as CriticInput)
Writes: case.critique  (approved + issues)
If not approved, the Coordinator sends the case back to the Explainer, which
sees the issues in ExplainerInput.critic_issues. The cap on that loop lives
in guardrails/loop_caps.py (cap_critic_loops, on the Explainer).
"""

from safespeak.agents.common import make_llm_agent
from safespeak.schemas import CaseRecord, CaseStatus, CriticInput, CriticReview

PROMPT = """You are the SafeSpeak Critic.
Check the explanation BEFORE it is shown to a non-technical user.
Reject it (approved=false) only for real problems, listing each in `issues`:
- It contradicts the verdict (e.g. says "safe" when the label is scam, or
  sounds certain when confidence is low).
- A reason in `why` is not supported by verdict.key_reasons or the parsed message.
- A step in `what_to_do` is vague, unsafe, or missing for a scam.
- It is not in the language given by parsed.language, or uses jargon.
If none apply, set approved=true and issues=[]."""


def build_input(case: CaseRecord) -> CriticInput:
    return CriticInput(parsed=case.parsed, verdict=case.verdict, explanation=case.explanation)


def create_critic(model=None):
    return make_llm_agent(
        name="critic",
        prompt=PROMPT,
        build_input=build_input,
        output_schema=CriticReview,
        section="critique",
        status=CaseStatus.EXPLAINED,
        model=model,
    )
