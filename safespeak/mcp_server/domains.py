"""Turn a URL / email / bare host into the host and its registrable domain.

  "https://login.sbi-kyc.co.in/x" -> host "login.sbi-kyc.co.in",
                                     registrable "sbi-kyc.co.in"
Registrable domain = what someone actually buys; WHOIS/RDAP is keyed on it.
Uses the public-suffix list bundled with tldextract (no network).
"""

from dataclasses import dataclass

import tldextract

# Zones newer than the bundled suffix list. RBI moved banks to .bank.in in 2025.
_EXTRA_SUFFIXES = ["bank.in", "fin.in"]
_extract = tldextract.TLDExtract(
    suffix_list_urls=(), include_psl_private_domains=True, extra_suffixes=_EXTRA_SUFFIXES
)


@dataclass(frozen=True)
class Domain:
    host: str
    registrable: str


def parse_domain(indicator: str) -> Domain | None:
    """None if the indicator has no usable domain (e.g. a bare IP or junk)."""
    text = indicator.strip().lower()
    if "@" in text and "/" not in text:  # email address -> its domain
        text = text.rsplit("@", 1)[1]
    parts = _extract(text)
    if not parts.suffix or not parts.domain:
        return None
    return Domain(host=parts.fqdn.removeprefix("www."), registrable=f"{parts.domain}.{parts.suffix}")
