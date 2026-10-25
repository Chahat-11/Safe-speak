"""Pattern specialist on hand-written messages (not copied from the datasets)."""

from safespeak.agents.pattern import match_patterns


def ids(text: str) -> list[str]:
    return [m.pattern_id for m in match_patterns(text)]


def test_otp_request_is_flagged_in_english_and_hinglish():
    assert "credential_request" in ids("Our agent will call you. Please share the OTP to stop the debit.")
    assert "credential_request" in ids("Sir aapka refund aa gaya, OTP [OTP] bhejo jaldi.")


def test_otp_advice_and_delivery_codes_are_not_requests():
    assert ids("Your OTP is [OTP]. Never share it with anyone, including bank staff.") == []
    assert ids("Out for delivery today. Share OTP [OTP] with the rider to receive the package.") == []
    assert ids("Aapka OTP [OTP] hai. Kisi ko mat batao.") == []


def test_prize_needs_a_claim_step_and_cashback_is_not_a_prize():
    assert "lottery_fee" in ids("You won Rs 25 lakh in the lucky draw! Pay Rs 999 processing fee to claim.")
    assert ids("You have received Rs 50 cashback, credited to your wallet.") == []


def test_power_cut_threat_needs_officer_or_tonight():
    assert "power_disconnection" in ids("Dear consumer, your electricity will be disconnected tonight at 9:30 pm. Call officer 9876500000.")
    assert ids("Your electricity bill of Rs 820 is due on 12-Nov. Pay before due date to avoid disconnection.") == []


def test_digital_arrest_threat_vs_police_advisory():
    assert "digital_arrest" in ids("CBI: an arrest warrant is issued in a money laundering case against your Aadhaar. Press 1.")
    assert ids("Beware of fake calls. Police never ask for money over video call.") == []


def test_government_link_is_not_a_phishing_cue():
    assert ids("Challan No. 123 for your vehicle is pending. Pay at https://echallan.parivahan.gov.in") == []
    assert "challan_link" in ids("Challan pending for your vehicle. Pay now at http://echallan-pay.top/x")


def test_match_lists_cues_and_strongest_first():
    matches = match_patterns("Your KYC is blocked! Update via http://kyc-fix.in or share the OTP with our agent.")
    assert matches[0].pattern_id == "credential_request"  # weight 0.95 sorts first
    kyc = next(m for m in matches if m.pattern_id == "account_block_threat")
    assert "blocking threat" in kyc.matched_cues and "link" in kyc.matched_cues
