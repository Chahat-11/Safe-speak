"""Reasoner: weighs the evidence on the blackboard and issues a Verdict.

Reads:  message_text + parsed + all specialist sections (as ReasonerInput)
Writes: case.verdict  (status -> REASONED)
May set needs_more_evidence; the loop cap lives in guardrails/loop_caps.py.
"""

from safespeak.agents.common import make_llm_agent
from safespeak.schemas import MAX_REASONER_LOOPS, CaseRecord, CaseStatus, ReasonerInput, Verdict

PROMPT = """You are the SafeSpeak Reasoner.
Decide whether the message is a scam. Your evidence is everything in INPUT:
the message itself (message_text), the parsed facts, and the specialists'
findings. An empty specialist list is NOT a reason to be uncertain; judge
the message itself.

How to weigh the evidence:
- Strong scam signs: a pattern match with weight >= 0.8; a verifier result
  "malicious"; the message asks you to share an OTP/PIN/password, pay a fee to
  receive money or a prize, transfer money, install an app, or contact a
  personal number to avoid a threat.
- Moderate signs: a pattern match below 0.8; a verifier result "suspicious"
  (young or lookalike domain); urgency or threats combined with a link.
- Signs of a legitimate message: it only informs (delivered, payment
  successful, appointment, balance, an OTP for an action you started that
  says not to share it) and asks for nothing risky. Treat that as
  likely_safe even with no specialist findings.
- "clean" or "unknown" verifier results do not prove a link is safe.

Labels and confidence:
- scam: one strong sign, or several moderate ones (confidence 0.75-0.95).
- suspicious: moderate signs only (0.55-0.75).
- likely_safe: informational and nothing risky is asked (0.6-0.9).
- uncertain: only when signs genuinely conflict (around 0.5).
key_reasons: short facts that point at specific evidence or words in the message.

Only set needs_more_evidence=true if evidence_rounds_left > 0 AND a specific
specialist could change your label (for example a link nobody has checked).
Do not request specialists in specialists_already_run unless that is the case."""


def build_input(case: CaseRecord) -> ReasonerInput:
    return ReasonerInput(
        message_text=case.message_text,
        parsed=case.parsed,
        specialists_already_run=case.routing.specialists if case.routing else [],
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
