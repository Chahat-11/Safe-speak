from safespeak.guardrails.critique_check import headline_issue
from safespeak.schemas import Verdict, VerdictLabel


def v(label: str) -> Verdict:
    return Verdict(label=VerdictLabel(label), confidence=0.8, key_reasons=["x"])


def test_safe_headline_for_scam_is_flagged():
    assert headline_issue(v("scam"), "This message is not a scam.")
    assert headline_issue(v("suspicious"), "This looks genuine.")


def test_scam_headline_for_likely_safe_is_flagged():
    assert headline_issue(v("likely_safe"), "This is a scam!")


def test_agreeing_headlines_pass():
    # the 3B Critic wrongly rejected exactly these kinds of headlines
    assert headline_issue(v("likely_safe"), "This message is not a scam.") is None
    assert headline_issue(v("scam"), "Warning: this is a scam.") is None
    assert headline_issue(v("uncertain"), "This may be a scam, be careful.") is None


def test_certain_headline_for_uncertain_is_flagged():
    assert headline_issue(v("uncertain"), "This is a scam.")
