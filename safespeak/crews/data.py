"""Everything the crews need that is plain code (no CrewAI, so it is unit tested).

The crews only ever see dev data or numbers. test_real.csv is refused here,
and guardrail events are reduced to counts because their text can quote messages.
"""

from __future__ import annotations

import csv
import json
import random
import re
from collections import defaultdict
from pathlib import Path

from safespeak.agents.pattern_matcher import match_patterns
from safespeak.guardrails.redaction import redact
from safespeak.schemas import (
    AgentTraceStats, MissedScams, PatternProposal, ProposalEvidence, TraceSummary,
)

DEV_FILE = Path("data/dev_synthetic.csv")
HARD_NEGATIVES = Path("data/hard_negatives_synthetic.csv")


def _masked_rows(path: Path, label: str) -> list[str]:
    if "test_real" in path.name:
        raise ValueError("test_real.csv is the held-out reporting set; crews may not read it.")
    with path.open(encoding="utf-8") as f:
        return [redact(r["message_text"])[0] for r in csv.DictReader(f) if r["label"] == label]


def missed_scams(n: int, seed: int = 0, path: Path = DEV_FILE) -> MissedScams:
    """A random sample of dev scams with no catalogue match."""
    missed = [text for text in _masked_rows(path, "scam") if not match_patterns(text)]
    return MissedScams(messages=random.Random(seed).sample(missed, min(n, len(missed))))


def proposal_matches(proposal: PatternProposal, text: str) -> bool:
    """Same rule as the catalogue: every group must have a phrase present."""
    return all(any(_phrase(p).search(text) for p in group) for group in proposal.cue_groups)


def _phrase(phrase: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(phrase.strip())}\b", re.IGNORECASE)


def measure(proposal: PatternProposal, dev: Path = DEV_FILE, negatives: Path = HARD_NEGATIVES) -> ProposalEvidence:
    """Code, not the LLM, decides how good a proposal is."""
    scams = _masked_rows(dev, "scam")
    legit = [*_masked_rows(dev, "legitimate"), *_masked_rows(negatives, "legitimate")]
    return ProposalEvidence(
        proposal=proposal,
        scam_hits=sum(proposal_matches(proposal, t) for t in scams),
        scam_total=len(scams),
        false_alarms=sum(proposal_matches(proposal, t) for t in legit),
        legit_total=len(legit),
    )


def summarise_trace(path: Path) -> TraceSummary:
    """Per-agent means and guardrail counts from logs/trace.jsonl."""
    durations, tokens, calls = defaultdict(float), defaultdict(int), defaultdict(int)
    guardrails: dict[str, int] = defaultdict(int)
    runs = 0
    for record in map(json.loads, path.read_text(encoding="utf-8").splitlines()):
        if record["kind"] == "run":
            runs += 1
            for m in record["metrics"]["agents"]:
                calls[m["agent"]] += m["calls"]
                durations[m["agent"]] += m["duration_ms"]
                tokens[m["agent"]] += m["prompt_tokens"] + m["completion_tokens"]
        elif record["kind"] == "agent" and record["name"] == "coordinator":
            for event in (record.get("output") or {}).get("guardrail_events", []):
                guardrails[f"{event['stage']}:{event['action']}"] += 1
    agents = [
        AgentTraceStats(agent=a, calls=c, mean_duration_ms=round(durations[a] / c, 1), mean_tokens=round(tokens[a] / c, 1))
        for a, c in calls.items() if c and a != "coordinator"  # its time includes every sub-agent
    ]
    return TraceSummary(runs=runs, agents=agents, guardrail_counts=dict(guardrails))
