"""Reasoner: weighs the evidence on the blackboard and issues a Verdict.

Reads:  parsed + all specialist sections (as ReasonerInput)
Writes: case.verdict  (status -> REASONED)
May set needs_more_evidence; the loop cap lives in guardrails/loop_caps.py.
"""

from safespeak.agents.common import make_llm_agent
from safespeak.schemas import MAX_REASONER_LOOPS, CaseRecord, CaseStatus, ReasonerInput, Verdict

PROMPT = """You are the SafeSpeak Reasoner.
Decide whether the message is a scam using ONLY the evidence in INPUT.
- label: scam, suspicious, likely_safe or uncertain.
- confidence: 0.0 to 1.0, how sure you are of the label.
- key_reasons: short, factual reasons that point at specific evidence.
- If the evidence is too thin to decide and evidence_rounds_left > 0, set
  needs_more_evidence=true and list which of verifier, pattern, retrieval,
  correlation should look again in requested_specialists."""


def build_input(case: CaseRecord) -> ReasonerInput:
    return ReasonerInput(
        parsed=case.parsed,
        verifier_findings=case.verifier_findings,
        pattern_matches=case.pattern_matches,
        retrieved_evidence=case.retrieved_evidence,
        correlation=case.correlation,
        evidence_rounds_left=MAX_REASONER_LOOPS - case.reasoner_loops,
    )


def create_reasoner(model=None):
    return make_llm_agent(
        name="reasoner",
        prompt=PROMPT,
        build_input=build_input,
        output_schema=Verdict,
        section="verdict",
        status=CaseStatus.REASONED,
        model=model,
    )
