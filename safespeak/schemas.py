"""Every typed contract in SafeSpeak.

Rule: no agent passes free text to another agent. Each agent reads the
CaseRecord (the blackboard) and writes exactly one of the models below
back into it. Pydantic validates every write, so a malformed LLM output
fails loudly at the boundary instead of leaking downstream.

Layout of this file follows the pipeline:
  1. shared enums
  2. intake          -> ParsedMessage
  3. routing         -> RoutingDecision
  4. specialists     -> VerifierFinding, PatternMatch, RetrievedEvidence,
                        CorrelationResult (+ small *Report wrappers)
  5. reasoning       -> Verdict
  6. explanation     -> Explanation, CriticReview
  7. guardrails      -> GuardrailEvent, GuardedInput
  8. the blackboard  -> CaseRecord
  9. agent inputs    -> ParserInput, VerifierInput, ReasonerInput,
                       ExplainerInput, CriticInput
 10. observability   -> AgentMetrics, RunMetrics
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

# Loop caps. Enforced in before_agent callbacks, never in prompts.
MAX_REASONER_LOOPS = 2
MAX_CRITIC_LOOPS = 2

# An LLM agent whose output fails validation is re-run this many times
# before the case fails. Each retry is recorded as a GuardrailEvent.
MAX_VALIDATION_RETRIES = 1


class Strict(BaseModel):
    """Base for all models: reject unknown fields so LLM drift is caught."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------
# 1. Shared enums
# --------------------------------------------------------------------------


class Channel(str, Enum):
    SMS = "sms"
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    SOCIAL = "social"
    UNKNOWN = "unknown"


class Specialist(str, Enum):
    VERIFIER = "verifier"
    PATTERN = "pattern"
    RETRIEVAL = "retrieval"
    CORRELATION = "correlation"


class CheckResult(str, Enum):
    MALICIOUS = "malicious"
    SUSPICIOUS = "suspicious"
    CLEAN = "clean"
    UNKNOWN = "unknown"


class VerdictLabel(str, Enum):
    SCAM = "scam"
    SUSPICIOUS = "suspicious"
    LIKELY_SAFE = "likely_safe"
    UNCERTAIN = "uncertain"


class CaseStatus(str, Enum):
    OPEN = "open"
    PARSED = "parsed"
    ROUTED = "routed"
    EVIDENCE_GATHERED = "evidence_gathered"
    REASONED = "reasoned"
    EXPLAINED = "explained"
    CLOSED = "closed"
    BLOCKED = "blocked"  # input or output guardrail stopped the case


# --------------------------------------------------------------------------
# 2. Intake / Parser output
# --------------------------------------------------------------------------


class ParsedMessage(Strict):
    """Structured view of the suspicious message, produced by Intake/Parser."""

    channel: Channel = Channel.UNKNOWN
    language: str = Field(default="en", description="e.g. 'en', 'hi' or 'hinglish'")
    sender: str | None = Field(default=None, description="Sender as shown, if any")
    claimed_organisation: str | None = Field(
        default=None, description="Who the message claims to be from, e.g. 'HDFC Bank'"
    )
    urls: list[str] = Field(default_factory=list)
    phone_numbers: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    requested_actions: list[str] = Field(
        default_factory=list, description="What the reader is asked to do, e.g. 'click link'"
    )
    urgency_cues: list[str] = Field(
        default_factory=list, description="Phrases creating pressure, e.g. 'within 24 hours'"
    )
    asks_for_credentials: bool = Field(
        default=False, description="Asks for OTP, PIN, password or card details"
    )


# --------------------------------------------------------------------------
# 3. Coordinator routing
# --------------------------------------------------------------------------


class RoutingDecision(Strict):
    """Which specialists the Coordinator dispatched, and why."""

    specialists: list[Specialist]
    rationale: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 4. Specialist outputs
# --------------------------------------------------------------------------


class VerifierFinding(Strict):
    """One check on one indicator (URL, phone, email, sender)."""

    indicator: str
    indicator_type: str = Field(description="url | phone | email | domain | sender")
    check: str = Field(description="e.g. 'blocklist', 'lookalike_domain', 'domain_age'")
    result: CheckResult
    detail: str
    source_tool: str = Field(description="MCP tool that produced this finding")


class PatternMatch(Strict):
    """A known scam pattern the message matches."""

    pattern_id: str
    pattern_name: str = Field(description="e.g. 'OTP harvesting', 'KYC update scam'")
    matched_cues: list[str] = Field(min_length=1)
    weight: float = Field(ge=0.0, le=1.0, description="How strongly this pattern implies fraud")


class RetrievedEvidence(Strict):
    """A similar known case or advisory pulled from the knowledge base."""

    source_id: str
    title: str
    snippet: str
    similarity: float = Field(ge=0.0, le=1.0)
    source: str = Field(description="Collection or feed it came from")


class CorrelationResult(Strict):
    """Links between this case and earlier cases (shared indicators, campaigns)."""

    related_case_ids: list[str] = Field(default_factory=list)
    shared_indicators: list[str] = Field(default_factory=list)
    campaign_id: str | None = None
    summary: str = ""


# Specialists return a list of items; ADK output_schema needs one model,
# so each list gets a thin wrapper.
class VerifierReport(Strict):
    findings: list[VerifierFinding] = Field(default_factory=list)


class PatternReport(Strict):
    matches: list[PatternMatch] = Field(default_factory=list)


class RetrievalReport(Strict):
    evidence: list[RetrievedEvidence] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 5. Reasoner output
# --------------------------------------------------------------------------


class Verdict(Strict):
    """The decision. The Reasoner may ask for more evidence (capped loop)."""

    label: VerdictLabel
    confidence: float = Field(ge=0.0, le=1.0)
    key_reasons: list[str] = Field(min_length=1)
    needs_more_evidence: bool = False
    requested_specialists: list[Specialist] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 6. Explainer / Critic outputs
# --------------------------------------------------------------------------


class Explanation(Strict):
    """Plain-language answer shown to the user."""

    headline: str = Field(description="One sentence: is it a scam?")
    why: list[str] = Field(min_length=1, description="Reasons in everyday words")
    what_to_do: list[str] = Field(min_length=1, description="Concrete next steps")


class CriticReview(Strict):
    """Critic's check of the Explanation against the Verdict."""

    approved: bool
    issues: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 7. Guardrail audit trail
# --------------------------------------------------------------------------


class GuardrailEvent(Strict):
    """Anything a guardrail callback did: block, redact, or rewrite."""

    stage: str = Field(description="input | output | model | tool")
    action: str = Field(description="allowed | blocked | redacted | replaced")
    reason: str
    at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GuardedInput(Strict):
    """What the input guardrail hands the Coordinator (raw text never leaves it)."""

    text: str = Field(description="Redacted message text")
    blocked: bool = False
    events: list[GuardrailEvent] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 8. The blackboard
# --------------------------------------------------------------------------


class CaseRecord(Strict):
    """The single shared record every agent reads from and writes to.

    Lives in ADK session state under one key (see blackboard.py).
    Sections start empty and are filled in pipeline order.
    """

    case_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: CaseStatus = CaseStatus.OPEN

    # Input (already redacted by the input guardrail; raw text is never stored)
    message_text: str

    # Pipeline sections
    parsed: ParsedMessage | None = None
    routing: RoutingDecision | None = None
    verifier_findings: list[VerifierFinding] = Field(default_factory=list)
    pattern_matches: list[PatternMatch] = Field(default_factory=list)
    retrieved_evidence: list[RetrievedEvidence] = Field(default_factory=list)
    correlation: CorrelationResult | None = None
    verdict: Verdict | None = None
    explanation: Explanation | None = None
    critique: CriticReview | None = None

    # Loop counters (read by before_agent callbacks to enforce caps)
    reasoner_loops: int = Field(default=0, ge=0)
    critic_loops: int = Field(default=0, ge=0)
    # Loops a cap callback has closed ("reasoner", "critic"). The Coordinator
    # reads this to stop looping; the callback is the only thing that sets it.
    capped_loops: list[str] = Field(default_factory=list)

    # Audit
    guardrail_events: list[GuardrailEvent] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 9. Agent inputs: the typed slice of the case each LLM agent is shown
# --------------------------------------------------------------------------


class ParserInput(Strict):
    message_text: str


class VerifierInput(Strict):
    domains: list[str] = Field(description="Hosts taken from the message's URLs and emails")


class ReasonerInput(Strict):
    parsed: ParsedMessage
    verifier_findings: list[VerifierFinding]
    pattern_matches: list[PatternMatch]
    retrieved_evidence: list[RetrievedEvidence]
    correlation: CorrelationResult | None
    evidence_rounds_left: int = Field(ge=0, description="0 means no more evidence can be requested")


class ExplainerInput(Strict):
    parsed: ParsedMessage
    verdict: Verdict
    critic_issues: list[str] = Field(default_factory=list)


class CriticInput(Strict):
    parsed: ParsedMessage
    verdict: Verdict
    explanation: Explanation


# --------------------------------------------------------------------------
# 10. Observability
# --------------------------------------------------------------------------


class AgentMetrics(Strict):
    """Totals for one agent across a single run (loops add up)."""

    agent: str
    calls: int = 0
    duration_ms: float = 0.0
    model_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class RunMetrics(Strict):
    """Per-agent cost/latency for one analysed message."""

    invocation_id: str
    case_id: str | None = None
    agents: list[AgentMetrics] = Field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return sum(a.prompt_tokens + a.completion_tokens for a in self.agents)
