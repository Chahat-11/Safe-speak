"""The two MCP tools, called as plain functions against the seeded cache."""

from safespeak.mcp_server.domains import parse_domain
from safespeak.mcp_server.reputation_tool import domain_reputation, lookalike_brand
from safespeak.mcp_server.whois_tool import domain_age
from safespeak.schemas import CheckResult
from tests.conftest import BLOCKLISTED
from tests.fake_llm import DOMAIN


def test_parse_domain_handles_urls_emails_and_bank_in():
    assert parse_domain("https://www.login.sbi-kyc.co.in/x").registrable == "sbi-kyc.co.in"
    assert parse_domain("alerts@hdfcbank.com").host == "hdfcbank.com"
    assert parse_domain("https://axis.bank.in").registrable == "axis.bank.in"
    assert parse_domain("not a domain") is None


def test_young_domain_is_suspicious_old_domain_is_clean():
    assert domain_age(f"http://{DOMAIN}/verify").result == CheckResult.SUSPICIOUS
    assert domain_age("https://www.hdfcbank.com").result == CheckResult.CLEAN


def test_unregistered_domain_is_suspicious():
    finding = domain_age("never-registered.in")
    assert finding.result == CheckResult.SUSPICIOUS and "not registered" in finding.detail


def test_blocklisted_host_and_its_subhost_are_malicious():
    assert domain_reputation(BLOCKLISTED).result == CheckResult.MALICIOUS
    assert domain_reputation(f"https://a.{BLOCKLISTED}/x").result == CheckResult.MALICIOUS


def test_sibling_host_on_same_domain_is_not_flagged():
    # Listing evil-login.example-phish.com must not flag all of example-phish.com.
    assert domain_reputation("example-phish.com").result == CheckResult.CLEAN


def test_lookalike_brand():
    assert lookalike_brand(parse_domain(DOMAIN)) == "hdfc"
    assert lookalike_brand(parse_domain("netbanking.hdfcbank.com")) is None
    assert domain_reputation(DOMAIN).result == CheckResult.SUSPICIOUS
