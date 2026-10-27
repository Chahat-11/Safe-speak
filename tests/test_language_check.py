from safespeak.guardrails.language_check import detect_language


def test_detects_english_hindi_and_hinglish():
    assert detect_language("Your account will be blocked today. Update KYC now.") == "en"
    assert detect_language("आपका खाता आज बंद हो जाएगा") == "hi"
    assert detect_language("Aapka KYC pending hai, jaldi update karo") == "hinglish"


def test_one_stray_word_is_not_hinglish():
    assert detect_language("Your order from Haldiram's will arrive aaj evening.") == "en"
