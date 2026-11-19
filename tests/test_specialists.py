"""Retrieval and Correlation, tested without ADK."""

import pytest

from safespeak import config
from safespeak.agents.retrieval_index import _index, search
from safespeak.case_history import correlate, indicators, record
from safespeak.schemas import CaseRecord, ParsedMessage, Verdict, VerdictLabel


def test_retrieval_finds_known_scams_for_a_lottery_scam():
    hits = search("Congratulations! You have won Rs 25 lakh in KBC lottery. Call to claim, pay processing fee.")
    assert hits and hits[0].title.startswith("Known scam")
    assert hits == sorted(hits, key=lambda e: -e.similarity)


def test_retrieval_returns_nothing_for_small_talk():
    assert search("hi how are you") == []


def test_retrieval_refuses_to_index_the_test_set(tmp_path):
    with pytest.raises(ValueError):
        _index(tmp_path / "test_real.csv")


def _case(case_id, urls=(), phones=(), label=VerdictLabel.SCAM) -> CaseRecord:
    return CaseRecord(
        case_id=case_id, message_text="x",
        parsed=ParsedMessage(urls=list(urls), phone_numbers=list(phones)),
        verdict=Verdict(label=label, confidence=0.9, key_reasons=["x"]),
    )


def test_indicators_are_registrable_domains_and_phone_digits():
    case = _case("a", urls=["http://login.sbi-kyc.in/x", "https://bit.ly/3xyz"], phones=["+91 98765-43210"])
    assert indicators(case) == ["9876543210", "sbi-kyc.in"]  # the shortener is not a campaign indicator


def test_correlation_finds_earlier_cases_sharing_a_number():
    record(_case("old1", phones=["9876543210"]))
    record(_case("old2", urls=["http://other.in"], label=VerdictLabel.LIKELY_SAFE))
    result = correlate(_case("new", urls=["http://sbi-kyc.in"], phones=["+919876543210"]))
    assert result.related_case_ids == ["old1"]
    assert result.shared_indicators == ["9876543210"]
    assert "1 judged scam" in result.summary


def test_history_stores_indicators_not_text():
    record(_case("a", urls=["http://sbi-kyc.in"]))
    stored = config.CASE_HISTORY_PATH.read_text()
    assert "sbi-kyc.in" in stored and "message_text" not in stored
