"""Case history: the memory behind the Correlation specialist.

After each analysed message, its indicators (registrable domains and phone
numbers) and the final verdict label are appended to a local JSONL file.
A new case is "correlated" when it shares an indicator with earlier cases:
the same scam link or number turning up again is how a scam wave shows.

Privacy: only indicators are stored, never message text or secrets (those
are already masked). The file stays on this machine and is git-ignored.
Caveat: earlier verdicts feed later ones, so one wrong verdict can echo.
That is why the Reasoner treats correlation as a moderate sign, not proof.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from safespeak import config
from safespeak.mcp_server.domains import is_shortener, parse_domain
from safespeak.schemas import CaseRecord, CorrelationResult

MAX_RELATED = 10


def indicators(case: CaseRecord) -> list[str]:
    """Registrable domains and 10-digit phone numbers named in the case."""
    if case.parsed is None:
        return []
    found = set()
    for item in [*case.parsed.urls, *case.parsed.emails]:
        domain = parse_domain(item)
        if domain and not is_shortener(domain):  # bit.ly is shared by everyone, not by a campaign
            found.add(domain.registrable)
    for phone in case.parsed.phone_numbers:
        digits = re.sub(r"\D", "", phone)[-10:]
        if len(digits) == 10:
            found.add(digits)
    return sorted(found)


def record(case: CaseRecord) -> None:
    """Remember this case's indicators and verdict for later correlation."""
    seen = indicators(case)
    if not seen or case.verdict is None:
        return
    entry = {"case_id": case.case_id, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "label": case.verdict.label.value, "indicators": seen}
    path = config.CASE_HISTORY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def correlate(case: CaseRecord) -> CorrelationResult:
    """Earlier cases that share an indicator with this one."""
    mine = set(indicators(case))
    related = [e for e in _history() if e["case_id"] != case.case_id and mine & set(e["indicators"])]
    if not related:
        checked = ", ".join(sorted(mine)) or "none"
        return CorrelationResult(summary=f"No earlier case shares these indicators ({checked}).")
    shared = sorted({i for e in related for i in e["indicators"] if i in mine})
    scams = sum(e["label"] in ("scam", "suspicious") for e in related)
    return CorrelationResult(
        related_case_ids=[e["case_id"] for e in related[-MAX_RELATED:]],
        shared_indicators=shared,
        campaign_id=f"wave:{shared[0]}",
        summary=f"Seen in {len(related)} earlier case(s), {scams} judged scam or suspicious; shared: {', '.join(shared)}.",
    )


def _history() -> list[dict]:
    path = config.CASE_HISTORY_PATH
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a half-written line must not break correlation
    return entries
