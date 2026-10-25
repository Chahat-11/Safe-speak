"""Tool 2: domain reputation = public phishing blocklists + lookalike check.

Blocklists (downloaded, cached for a day, matched locally — the domain is
never sent anywhere):
  - OpenPhish community feed   (recent phishing URLs)
  - Phishing.Database ACTIVE   (large list of active phishing hosts)
Hosts are matched exactly or as a sub-host of a listed host, walking up only
to the registrable domain, so one bad *.vercel.app site does not flag all of
vercel.app.

Lookalike: the domain contains a brand name (e.g. "sbi") but is not one of
that brand's official domains. Keyword match, so it can misfire (e.g.
"taxis" contains "axis"); that is why it gives "suspicious", not "malicious".
Not on a blocklist does NOT mean safe; the detail text says so.
"""

from urllib.parse import urlparse

import httpx

from safespeak import config
from safespeak.mcp_server.cache import cache_path, is_fresh
from safespeak.mcp_server.domains import Domain, parse_domain
from safespeak.schemas import CheckResult, VerifierFinding

FEEDS = {
    "openphish": "https://raw.githubusercontent.com/openphish/public_feed/refs/heads/main/feed.txt",
    "phishing_database": "https://raw.githubusercontent.com/Phishing-Database/Phishing.Database/master/phishing-domains-ACTIVE.txt",
}

# brand keyword -> official domains (host must equal one or be a sub-host of one)
OFFICIAL_DOMAINS = {
    "sbi": ["sbi.co.in", "onlinesbi.sbi", "sbi.bank.in", "sbicard.com"],
    "hdfc": ["hdfcbank.com", "hdfc.com", "hdfcbank.bank.in"],
    "icici": ["icicibank.com", "icici.bank.in"],
    "axis": ["axisbank.com", "axis.bank.in"],
    "kotak": ["kotak.com", "kotak.bank.in"],
    "paytm": ["paytm.com", "paytmbank.com"],
    "amazon": ["amazon.in", "amazon.com"],
    "flipkart": ["flipkart.com"],
    "indiapost": ["indiapost.gov.in"],
    "incometax": ["incometax.gov.in"],
    "epfo": ["epfindia.gov.in"],
    "airtel": ["airtel.in"],
}


def domain_reputation(indicator: str) -> VerifierFinding:
    domain = parse_domain(indicator)
    if domain is None:
        return _finding(indicator, CheckResult.UNKNOWN, "Not a domain name.")

    hits, failed = _blocklist_hits(domain)
    if hits:
        return _finding(indicator, CheckResult.MALICIOUS, f"{domain.host} is on blocklist(s): {', '.join(hits)}.")
    brand = lookalike_brand(domain)
    if brand:
        detail = f"{domain.host} uses the name '{brand}' but is not an official {brand} domain."
        return _finding(indicator, CheckResult.SUSPICIOUS, detail)
    if failed == len(FEEDS):
        return _finding(indicator, CheckResult.UNKNOWN, "Blocklists could not be loaded.")
    return _finding(indicator, CheckResult.CLEAN, f"{domain.host} not on {len(FEEDS) - failed} blocklist(s); this does not prove it is safe.")


def lookalike_brand(domain: Domain) -> str | None:
    for brand, official in OFFICIAL_DOMAINS.items():
        if brand in domain.host and not any(_is_same_or_sub(domain.host, o) for o in official):
            return brand
    return None


def _blocklist_hits(domain: Domain) -> tuple[list[str], int]:
    """(names of feeds listing this host, number of feeds that failed to load)."""
    candidates = _hosts_up_to_registrable(domain)
    hits, failed = [], 0
    for name in FEEDS:
        hosts = _load_feed(name)
        if hosts is None:
            failed += 1
        elif candidates & hosts:
            hits.append(name)
    return hits, failed


def _hosts_up_to_registrable(domain: Domain) -> set[str]:
    """login.a.evil.com -> {login.a.evil.com, a.evil.com, evil.com}"""
    labels = domain.host.split(".")
    depth = len(domain.registrable.split("."))
    return {".".join(labels[i:]) for i in range(len(labels) - depth + 1)}


def _load_feed(name: str) -> set[str] | None:
    path = cache_path("feeds", f"{name}.txt")
    if not is_fresh(path, config.FEED_TTL_HOURS):
        try:
            response = httpx.get(FEEDS[name], follow_redirects=True, timeout=30)
            response.raise_for_status()
            path.write_text(response.text)
        except httpx.HTTPError:
            if not path.exists():
                return None  # no stale copy to fall back on
    return {_host_of(line) for line in path.read_text().splitlines() if line.strip()}


def _host_of(line: str) -> str:
    """Feeds mix full URLs and bare hosts; reduce both to a lowercase host."""
    line = line.strip().lower()
    host = urlparse(line).hostname if "://" in line else line
    return (host or "").removeprefix("www.")


def _is_same_or_sub(host: str, official: str) -> bool:
    return host == official or host.endswith("." + official)


def _finding(indicator: str, result: CheckResult, detail: str) -> VerifierFinding:
    return VerifierFinding(
        indicator=indicator, indicator_type="domain", check="reputation",
        result=result, detail=detail, source_tool="domain_reputation",
    )
