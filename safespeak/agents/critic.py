"""Critic: reviews the Explanation against the Verdict before it reaches the user.

Reads:  parsed + verdict + explanation   (as CriticInput)
Writes: case.critique  (approved + issues)
If not approved, the Coordinator sends the case back to the Explainer, which
sees the issues in ExplainerInput.critic_issues. The cap on that loop lives
in guardrails/loop_caps.py (cap_critic_loops, on the Explainer).
Each issue is tagged with the check that failed ("[unsupported] ...").
guardrails/critique_check.py then verifies the tags in code: only problems
a code check confirms send the explanation back.
"""

from safespeak.agents.common import make_llm_agent
from safespeak.guardrails.critique_check import ground_critique
from safespeak.schemas import CaseRecord, CaseStatus, CriticInput, CriticReview

PROMPT = """You are the SafeSpeak Critic. Check the explanation against the
verdict and the parsed message. Run these checks:

1. contradiction: the headline says the opposite of verdict.label (e.g. "not a
   scam" when the label is scam), or sounds certain when the label is uncertain.
2. unsupported: a "why" reason states something the message does not contain
   (e.g. mentions a link or a phone number that is not in the message).
3. vague: a "what_to_do" step is too vague to act on.
4. language: the text is not in the language of parsed.language, or uses jargon.

Put ONLY checks that FAILED in `issues`. Start each issue with the check name in
square brackets, then say what to fix. Never list a check that passed.
If no check failed: {"approved": true, "issues": []}.

Example of a failed check:
{"approved": false, "issues": ["[unsupported] The second reason says they sent a link, but the message has no link."]}"""


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
        checks=[ground_critique],
    )
