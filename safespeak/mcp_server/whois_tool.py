"""Tool 1: domain age via RDAP (the JSON successor to WHOIS).

rdap.org redirects to the registry for each TLD (Verisign for .com, NIXI
for .in). Only the domain name is sent, never message text.
Scam domains are usually days or weeks old; real banks' are decades old.
"""

import json
from datetime import datetime, timezone

import httpx

from safespeak import config
from safespeak.mcp_server.cache import cache_path, is_fresh
from safespeak.mcp_server.domains import parse_domain
from safespeak.schemas import CheckResult, VerifierFinding

RDAP_URL = "https://rdap.org/domain/{domain}"
YOUNG_DOMAIN_DAYS = 90


def domain_age(indicator: str) -> VerifierFinding:
    domain = parse_domain(indicator)
    if domain is None:
        return _finding(indicator, CheckResult.UNKNOWN, "Not a domain name.")
    try:
        record = _rdap_record(domain.registrable)
    except httpx.HTTPError as err:
        return _finding(indicator, CheckResult.UNKNOWN, f"RDAP lookup failed: {type(err).__name__}.")
    return _judge_age(indicator, domain.registrable, record)


def _judge_age(indicator: str, registrable: str, record: dict | None) -> VerifierFinding:
    if record is None:
        return _finding(indicator, CheckResult.SUSPICIOUS, f"{registrable} is not registered (RDAP 404).")
    registered = _registration_date(record)
    if registered is None:
        return _finding(indicator, CheckResult.UNKNOWN, f"No registration date published for {registrable}.")
    days = (datetime.now(timezone.utc) - registered).days
    when = f"{registrable} registered {registered:%Y-%m-%d} ({days} days ago)."
    result = CheckResult.SUSPICIOUS if days < YOUNG_DOMAIN_DAYS else CheckResult.CLEAN
    return _finding(indicator, result, when)


def _rdap_record(registrable: str) -> dict | None:
    """Cached RDAP JSON, or None if the registry says the domain does not exist."""
    path = cache_path("rdap", f"{registrable}.json")
    if not is_fresh(path, config.RDAP_TTL_HOURS):
        response = httpx.get(RDAP_URL.format(domain=registrable), follow_redirects=True, timeout=15)
        if response.status_code not in (200, 404):
            response.raise_for_status()
        path.write_text(response.text if response.status_code == 200 else "null")
    return json.loads(path.read_text())


def _registration_date(record: dict) -> datetime | None:
    for event in record.get("events", []):
        if event.get("eventAction") == "registration":
            return datetime.fromisoformat(event["eventDate"].replace("Z", "+00:00"))
    return None


def _finding(indicator: str, result: CheckResult, detail: str) -> VerifierFinding:
    return VerifierFinding(
        indicator=indicator, indicator_type="domain", check="domain_age",
        result=result, detail=detail, source_tool="domain_age",
    )
