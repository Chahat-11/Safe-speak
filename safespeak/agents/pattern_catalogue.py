"""Catalogue of known Indian scam patterns, used by the Pattern specialist.

Each pattern is a COMBINATION of cues, never one scary word: real banks also
say "avoid disconnection" and every OTP message mentions "OTP". A pattern
matches only when ALL its `required` cues appear; `supporting` cues add
weight. Cues are plain regexes with a human-readable name, and the name is
what goes into PatternMatch.matched_cues.

Built from public scam typologies (RBI, CERT-In, I4C advisories), checked
against dev_synthetic.csv and hard_negatives_synthetic.csv only — never
against test_real.csv (see scripts/pattern_coverage.py).
"""

import re
from dataclasses import dataclass, field


def _rx(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# ---- reusable cues ---------------------------------------------------------

LINK = _rx(r"https?://|www\.|\bbit\.ly|\[[^\]]*link\]|\bclick\b|\blink\b|\btap here\b")
PAY = _rx(r"\bpay\b|\bfee\b|\bcharges?\b|\bdeposit\b|\btransfer\b|\bprocessing\b|\btax\b")
CALL_OR_CHAT = _rx(r"\bcall\b|\bcontact\b|\bwhats ?app\b|\btelegram\b|\bpress \d\b|\bdial\b")
# A personal mobile number (+91 / 10 digits from 6-9, masked digits allowed).
# Toll-free 1800/1860 helplines do not match.
MOBILE = _rx(r"(?<![\d-])(?:\+91[\s-]?)?[6-9]\d{3}[\dX]{6}(?![\d])")
# Warnings and advice ("Do not click suspicious links", "Never share OTP").
NEGATION = _rx(r"\b(?:do not|don't|dont|never|not to|beware|mat|nahi|na kare)\b")
URGENT_TIME = _rx(r"\btonight\b|\btoday\b|\bwithin \d+ ?(?:hours?|hrs|minutes?|mins)\b|\bimmediately\b|\b\d{1,2}[:.]\d{2} ?(?:am|pm)\b")


# Government domains (*.gov.in, *.nic.in) cannot be registered privately, so a
# link to one is not a phishing cue. The matcher hides such links before
# checking cues; whether a link is safe overall is still the Verifier's job.
OFFICIAL_LINK = _rx(r"(?:https?://)?(?:[\w-]+\.)+(?:gov|nic)\.in\b\S*")


@dataclass(frozen=True)
class ScamPattern:
    id: str
    name: str
    weight: float  # how strongly a match implies fraud (0-1)
    required: dict[str, re.Pattern[str]]
    supporting: dict[str, re.Pattern[str]] = field(default_factory=dict)
    # A required cue does not count if its sentence matches `exempt`,
    # e.g. "Never share your OTP" is advice, not a request.
    exempt: re.Pattern[str] | None = None


PATTERNS: list[ScamPattern] = [
    ScamPattern(
        id="credential_request",
        name="Asks you to share an OTP, PIN, password or card details",
        weight=0.95,
        required={
            "asks to share a secret": _rx(
                r"\b(?:share|send|tell|give|provide|forward|read out|enter)\b[^.!?\n]{0,25}"
                r"\b(?:otp|pin|password|cvv|card (?:number|details)|\[otp\])"
                # Hinglish puts the verb after the secret: "OTP bhejo", "PIN batao"
                r"|\b(?:otp|pin|password|cvv)\b[^.!?\n]{0,15}\b(?:bhejo|bhej do|batao|bata do|share karo|send karo|de do)\b"
            ),
        },
        # Advice ("never share") and doorstep delivery codes ("share OTP with
        # the rider") are normal; scams ask you to send it to a person/caller.
        exempt=_rx(NEGATION.pattern + r"|\brider\b|\b(?:at|for) (?:the time of )?delivery\b|\bdelivery (?:agent|executive|partner|boy)\b"
                   r"|\bonly (?:if|when|after) you receive\b"),
    ),
    ScamPattern(
        id="lottery_fee",
        name="Prize or lottery that needs a payment to claim",
        weight=0.9,
        required={
            "prize or lottery win": _rx(r"\bwon\b|\bwinner\b|\blucky draw\b|\blottery\b|\bjackpot\b|\bprize\b|\bkbc\b"),
            "payment to claim": PAY,
        },
        supporting={"claim instruction": _rx(r"\bclaim\b|\bto receive\b|\bredeem\b|\bcollect\b")},
    ),
    ScamPattern(
        id="prize_contact",
        name="Unexpected prize you must call, click or reply to claim",
        weight=0.75,
        required={
            "prize or lottery win": _rx(r"\bwon\b|\bwinner\b|\blucky draw\b|\blottery\b|\bjackpot\b|\bkbc\b|\bprize\b|\breward\b|\bgift\b"),
            "contact or link to claim": _rx(r"\bcall\b|\bcontact\b|\bwhats ?app\b|\breply\b|\bclaim\b|https?://|\[[^\]]*link\]|\bclick\b"),
        },
        # Real cashback / loyalty points are already credited, not "claimed".
        exempt=_rx(r"\bcashback\b|\bcredited\b|\bsupercoins?\b|\breward points\b|\bhas been added\b"),
    ),
    ScamPattern(
        id="digital_arrest",
        name="Fake police / court / agency threat (digital arrest)",
        weight=0.9,
        required={
            "claims to be an authority": _rx(
                r"\bpolice\b|\bcbi\b|\bcrime branch\b|\bcyber cell\b|\bnarcotics\b|\bncb\b|\benforcement directorate\b"
                r"|\bcourt\b|\bcustoms\b|\btrai\b|\bmumbai police\b|\binvestigation\b"
            ),
            "threat of legal action": _rx(
                r"\barrest\b|\bwarrant\b|\bfir\b|\bmoney laundering\b|\bterror\b|\billegal\b|\bdrugs?\b"
                r"|\bseized\b|\bcriminal case\b|\blegal action\b|\bcase (?:registered|filed)\b"
            ),
        },
        supporting={"demands payment": PAY, "call or press a key": CALL_OR_CHAT},
        exempt=NEGATION,  # "Beware... Police never ask for money" is an advisory
    ),
    ScamPattern(
        id="safe_account_transfer",
        name="Asks you to move your money for an 'audit' or to a 'safe account'",
        weight=0.9,
        required={
            "move your money": _rx(r"\btransfer (?:all )?(?:your )?(?:funds|money|balance|amount|savings)\b"),
            "pretext": _rx(r"\baudit\b|\bsafe account\b|\bsecure account\b|\bverification\b|\binvestigation\b|\bfrozen\b|\bRBI\b"),
        },
    ),
    ScamPattern(
        id="account_block_threat",
        name="Account / KYC / SIM will be blocked unless you act",
        weight=0.75,
        required={
            "account or KYC": _rx(r"\bkyc\b|\bpan\b|\baadhaa?r\b|\baccount\b|\bnet ?banking\b|\blogin\b|\bsim\b|\bwallet\b|\bupi\b|\bmobile number\b"),
            "blocking threat": _rx(
                r"\bblock(?:ed)?\b|\bsuspen\w*|\bdeactivat\w*|\bfrozen\b|\bfreeze\b|\bwill be closed\b"
                r"|\bexpir(?:e|es|ed|y)\b|\bterminat\w*|\bdisabled?\b|\brejected\b"
                r"|\b(?:services|access) (?:are |is |has been )?(?:limited|restricted)\b|\brestore\b"
            ),
            "asks you to act": _rx(r"\bupdate\b|\bverify\b|\bclick\b|\bcall\b|\blink\b|\bre-?kyc\b|\bsubmit\b|\bre-?upload\b|\bpress\b"),
        },
        supporting={"link": LINK, "urgent deadline": URGENT_TIME},
    ),
    ScamPattern(
        id="power_disconnection",
        name="Electricity will be cut tonight unless you call an 'officer'",
        weight=0.85,
        required={
            "electricity": _rx(r"\belectricity\b|\bpower\b|\bbijli\b|\blight bill\b|\belectric\b|\beb\b"),
            "disconnection threat": _rx(r"\bdisconnect\w*|\bcut\b|\bcut ?off\b"),
            "officer, mobile number or tonight's deadline": _rx(
                r"\bofficer\b|\bwhats ?app\b|\btonight\b|\btoday at\b|\b\d{1,2}[:.]\d{2} ?(?:am|pm)\b|" + MOBILE.pattern
            ),
        },
    ),
    ScamPattern(
        id="parcel_problem_fee",
        name="Parcel held / failed delivery that needs a fee or address update",
        weight=0.75,
        required={
            "parcel or delivery": _rx(r"\bparcel\b|\bpackage\b|\bshipment\b|\bcourier\b|\bdelivery\b|\bconsignment\b|\border\b"),
            "delivery problem": _rx(
                r"\bheld\b|\bon hold\b|\bdelayed\b|\bincomplete address\b|\bcould not be delivered\b|\bfailed\b"
                r"|\bcustoms\b|\bstorage fee\b|\bre-?delivery\b|\breturned\b|\bat the depot\b|\bupdate (?:your )?address\b"
                r"|\bconfirm (?:your )?identity\b|\baddress (?:is )?(?:not )?verified\b|\bstuck\b|\bincomplete payment\b"
            ),
            "asks you to pay, click or verify": _rx(PAY.pattern + "|" + LINK.pattern + r"|\bverif\w*|\bconfirm\b"),
        },
    ),
    ScamPattern(
        id="challan_link",
        name="Traffic challan with a payment link or a threat",
        weight=0.65,
        required={
            "traffic challan": _rx(r"\bchallans?\b|\btraffic (?:fine|violation|police)\b|\boverspeeding\b|\brto\b"),
            "link or threat": _rx(
                LINK.pattern + r"|\bsuspen\w*|\bconfiscat\w*|\bseiz\w*|\bblacklist\w*|\blegal action\b"
            ),
        },
        supporting={"payment": PAY},
    ),
    ScamPattern(
        id="chat_app_job",
        name="Job offer handled over WhatsApp / Telegram",
        weight=0.7,
        required={
            "job offer": _rx(r"\bjob\b|\bwork[- ]from[- ]home\b|\bpart[- ]time\b|\bhiring\b|\bvacancy\b|\brole\b|\bselected\b|\bapplication\b|\binterview\b"),
            "chat-app contact": _rx(r"\bwhats ?app\b|\btelegram\b"),
        },
    ),
    ScamPattern(
        id="job_fee",
        name="Job offer that asks you to pay first",
        weight=0.85,
        required={
            "job offer": _rx(r"\bjob\b|\bwork[- ]from[- ]home\b|\bpart[- ]time\b|\bhiring\b|\bvacancy\b|\brole\b|\bshortlisted\b|\binterview\b|\boffer letter\b"),
            "fee to start": _rx(r"\bregistration fee\b|\btraining (?:kit|fee)\b|\bsecurity deposit\b|\bpay\b[^.!?\n]{0,15}(?:rs\.?|₹|inr)\s?\d"),
        },
    ),
    ScamPattern(
        id="easy_earnings",
        name="Promise of easy daily / per-task earnings",
        weight=0.8,
        required={
            "earn money for easy tasks": _rx(
                r"\bearn\b[^.!?\n]{0,25}(?:rs\.?|₹|inr|\$|€|euros?|dollars?|\d)|\bearn (?:money|income)\b"
                r"|\b(?:like|rate|rating|review)\w*\b[^.!?\n]{0,30}\b(?:videos?|hotels?|products?|posts?)\b[^.!?\n]{0,30}\b(?:earn|paid|money)\b"
            ),
        },
        supporting={"per day / per task": _rx(r"\bdaily\b|\bper day\b|\bper task\b|\bper hour\b|\bfrom home\b")},
    ),
    ScamPattern(
        id="task_investment",
        name="Invest a small amount to get a bigger return or bonus",
        weight=0.85,
        required={
            "invest or deposit": _rx(r"\binvest\w*|\bdeposit\b|\brecharge\b|\b(?:send|pay)\b[^.!?\n]{0,10}(?:rs\.?|₹|inr)\s?\d"),
            "promised return": _rx(r"\breceive\b|\breturns?\b|\bprofit\b|\bbonus\b|\bdouble\b|\bguaranteed\b"),
        },
    ),
    ScamPattern(
        id="tax_refund_link",
        name="Tax refund / GST notice that sends you to a link",
        weight=0.7,
        required={
            "tax or refund": _rx(r"\bincome tax\b|\btax refund\b|\bit refund\b|\bitr\b|\bgst\b|\btds\b|\brefund\b"),
            "link or update request": _rx(r"https?://|\[[^\]]*link\]|\bclick\b|\bupdate\s+(?:\w+\s+)?(?:details|bank\w*|pan\w*|kyc)\b|\bdownload (?:the )?attached\b"),
        },
        supporting={"threat": _rx(r"\bsuspend\w*|\bcancel\w*|\bpenalty\b|\bblock\w*")},
        exempt=NEGATION,
    ),
    ScamPattern(
        id="qr_code_payment",
        name="Asks you to scan a QR code (to pay or to 'receive' money)",
        weight=0.8,
        required={"scan a QR code": _rx(r"\bscan\b[^.!?\n]{0,20}\bqr\b|\bqr code\b[^.!?\n]{0,25}\b(?:pay|receive|claim)\b")},
    ),
    ScamPattern(
        id="remote_access_app",
        name="Asks you to install a screen-sharing or unknown app",
        weight=0.85,
        required={"remote access or APK": _rx(r"\banydesk\b|\bteamviewer\b|\bquick ?support\b|\brustdesk\b|\.apk\b|\bscreen shar\w*")},
    ),
]

