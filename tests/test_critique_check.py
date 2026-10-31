from safespeak.guardrails.critique_check import headline_issue, unsupported_claims
from safespeak.schemas import CaseRecord, Explanation, ParsedMessage, Verdict, VerdictLabel


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


def case_with(message: str, why: list[str], parsed: ParsedMessage | None = None) -> CaseRecord:
    return CaseRecord(
        message_text=message,
        parsed=parsed or ParsedMessage(),
        verdict=v("scam"),
        explanation=Explanation(headline="This is a scam.", why=why, what_to_do=["Ignore it."]),
    )


def test_invented_link_and_number_are_flagged():
    case = case_with("Pay customs duty of Rs 2800 to release your parcel.",
                     ["They included a link in the message.", "They ask you to call a specific number."])
    assert len(unsupported_claims(case)) == 2


def test_real_link_and_number_are_not_flagged():
    case = case_with("Pay now at http://x-pay.top or call 9876543210",
                     ["They included a link.", "They ask you to call a specific number."],
                     ParsedMessage(urls=["http://x-pay.top"], phone_numbers=["9876543210"]))
    assert unsupported_claims(case) == []


def test_reasons_saying_there_is_no_link_are_not_flagged():
    case = case_with("DTDC: Article successfully delivered to recipient.",
                     ["It does not contain any links.", "There are no links present.",
                      "It doesn't ask you to click anything or call a number."])
    assert unsupported_claims(case) == []
