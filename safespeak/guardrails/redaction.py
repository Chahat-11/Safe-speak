"""Mask secrets (OTPs, card, account and Aadhaar numbers) before they are stored.

Phone numbers, URLs and emails are NOT masked: they are the evidence the
Verifier needs. Plain regexes on purpose: easy to read, test and extend.
Order matters: the more specific patterns (cards, Aadhaar) run first.
For OTP/account rules, group 1 keeps the keyword ("OTP is") and only the
number after it is replaced.
"""

import re

# (label, pattern). The label becomes the placeholder, e.g. "[OTP]".
_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("CARD", re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b")),
    ("AADHAAR", re.compile(r"\b\d{4} \d{4} \d{4}\b")),
    ("ACCOUNT", re.compile(r"(?i)(\b(?:a/c|acct|account)\b[\s:.#-]*(?:no\.?|number)?[\s:#-]*)[xX*]*\d{3,18}")),
    ("OTP", re.compile(r"(?i)(\b(?:otp|code|pin|passcode)\b\D{0,15}?)\b\d{4,8}\b")),
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
