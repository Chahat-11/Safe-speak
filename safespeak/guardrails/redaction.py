"""Mask secrets (OTPs, PINs, CVVs, passwords, card, account, Aadhaar, PAN) before they are stored.

Phone numbers, URLs, emails and money amounts are NOT masked: they are the
evidence the Verifier and Reasoner need. Plain regexes on purpose: easy to
read, test and extend. Order matters: the more specific patterns (cards,
Aadhaar) run first. Rules with a capture group keep the keyword ("OTP is")
and replace only the secret after it.

Secrets are written many ways in real messages, so the rules accept:
  - digits split by spaces or dashes ("4 8 2 9 1 3", "482-913"),
  - the number before the keyword ("482913 is your OTP"),
  - Hindi keywords (ओटीपी, खाता) and Hinglish ones (khata).
"""

import re

# 4-8 digits, optionally split by single spaces or dashes: 482913, 4 8 2 9 1 3, 482-913
_CODE = r"\d(?:[ -]?\d){3,7}"
# Whole words only, so "pincode 110001" (a postal code) is left alone.
_CODE_WORD = r"(?:(?<![a-z])(?:otp|one[- ]time password|verification code|code|m?pin|passcode)(?![a-z])|ओटीपी|पिन|कोड)"

# (label, pattern). The label becomes the placeholder, e.g. "[OTP]".
_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("CARD", re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b|\b\d{4}[ -]?\d{6}[ -]?\d{5}\b")),  # 16-digit and 15-digit (Amex)
    ("AADHAAR", re.compile(r"\b\d{4}[ -]\d{4}[ -]\d{4}\b")),
    ("AADHAAR", re.compile(r"(?i)(\b(?:aadhaa?r|uid)\b\D{0,15}?)\b\d{12}\b")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("ACCOUNT", re.compile(r"(?i)((?:\b(?:a/c|acct|account|khata)\b|खाता)[\s:.#-]*(?:no\.?|number|sankhya|संख्या)?[\s:#-]*)[xX*]*\d{3,18}")),
    ("CVV", re.compile(r"(?i)(\b(?:cvv|cvc)\b\D{0,10}?)\b\d{3,4}\b")),
    ("PASSWORD", re.compile(r"(?i)(\b(?:password|passwd|pwd)\b\s*(?:is|:|=)\s*)\S+")),
    # "OTP for txn of Rs 2500 is 774411": the code is the number after "is", not the amount.
    ("OTP", re.compile(rf"(?i)({_CODE_WORD}[^\n]{{0,40}}?\b(?:is|:|=)\s*)(?<!\d){_CODE}(?!\d)")),
    ("OTP", re.compile(rf"(?i)({_CODE_WORD}\D{{0,15}}?)(?<!₹)(?<!rs )(?<!rs\. )(?<!inr )(?<!\d){_CODE}(?!\d)")),
    # Number first: "482913 is your OTP". Not after a currency sign, so "Rs 5000 code" stays.
    ("OTP", re.compile(rf"(?i)(?<![\d₹.,])(?<!rs )(?<!rs\.)(?<!inr )\b{_CODE}\b(?=\s*(?:is|=|:)?\s*(?:your|the|ur)?\s*{_CODE_WORD})")),
]


def redact(text: str) -> tuple[str, list[str]]:
    """Return (masked text, labels of what was masked)."""
    found: list[str] = []
    for label, pattern in _RULES:
        keep_prefix = pattern.groups > 0
        replacement = rf"\1[{label}]" if keep_prefix else f"[{label}]"
        text, count = pattern.subn(replacement, text)
        found.extend([label] * count)
    return text, found
