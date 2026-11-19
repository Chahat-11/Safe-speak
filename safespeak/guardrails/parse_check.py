"""Parser grounding: after_agent callback on the Parser.

"The LLM proposes, code confirms", applied to extraction. qwen2.5:3b copies
the examples from its schema into real cases: "HDFC Bank" as the sender of a
message that never names a bank, "within 24 hours" as an urgency cue, and
"click link" for a message with no link. Those invented facts then steer the
routing and the verdict.

So every extracted fact must be found in the message text, or it is removed:
  urls, emails        -> must appear in the text
  phone_numbers       -> their digits must appear in the text
  claimed_organisation-> one of its words must appear in the text
  urgency_cues        -> must appear in the text
  requested_actions   -> link/click actions only if the message has a link
  asks_for_credentials-> only if the text mentions a secret
Anything removed is logged as a GuardrailEvent.
"""

import re

from google.adk.agents.callback_context import CallbackContext

from safespeak.agents.pattern_catalogue import LINK
from safespeak.blackboard import log_guardrail, post, read_case
from safespeak.schemas import ParsedMessage

_LINK_ACTION = re.compile(r"(?i)\b(click|link|url|website|tap)\b")
_SECRET = re.compile(
    r"(?i)\b(otp|m?pin|password|cvv|card|account|a/c|bank details|kyc|aadhaa?r|pan|credentials?|login)\b"
    r"|\[(OTP|CARD|ACCOUNT|CVV|PASSWORD|AADHAAR|PAN)\]|ओटीपी|पिन|पासवर्ड"
)
# Words too common to prove an organisation is named ("Bank" alone is not "HDFC Bank").
_GENERIC = {"bank", "the", "ltd", "limited", "india", "indian", "of", "and", "pvt", "private", "services", "team"}


def ground_parsed(callback_context: CallbackContext) -> None:
    state = callback_context.state
    case = read_case(state)
    if case.parsed is None:
        return
    grounded, removed = ground(case.parsed, case.message_text)
    if removed:
        post(state, "parsed", grounded)
        log_guardrail(state, "agent", "replaced", "Parser listed things not in the message: " + "; ".join(removed)[:300])


def ground(parsed: ParsedMessage, text: str) -> tuple[ParsedMessage, list[str]]:
    """Pure function (easy to test): (parsed facts found in the text, what was removed)."""
    lower = text.lower()
    digits = re.sub(r"\D", "", text)
    has_link = bool(LINK.search(text))
    keep = {
        "urls": [u for u in parsed.urls if _url_in(u, lower)],
        "emails": [e for e in parsed.emails if e.lower() in lower],
        "phone_numbers": [p for p in parsed.phone_numbers if _phone_in(p, digits)],
        "urgency_cues": [c for c in parsed.urgency_cues if c.lower() in lower],
        "requested_actions": [a for a in parsed.requested_actions if has_link or not _LINK_ACTION.search(a)],
        "claimed_organisation": parsed.claimed_organisation if _org_in(parsed.claimed_organisation, lower) else None,
        "asks_for_credentials": parsed.asks_for_credentials and bool(_SECRET.search(text)),
    }
    removed = []
    for field, value in keep.items():
        before = getattr(parsed, field)
        if isinstance(before, list):
            removed += [f"{field}: {item!r}" for item in before if item not in value]
        elif before != value:
            removed.append(f"{field}: {before!r}")
    return parsed.model_copy(update=keep), removed


def _url_in(url: str, lower: str) -> bool:
    bare = re.sub(r"^https?://", "", url.lower()).rstrip("/")
    return bool(bare) and bare in lower


def _phone_in(phone: str, digits: str) -> bool:
    wanted = re.sub(r"\D", "", phone)[-10:]
    return len(wanted) >= 5 and wanted in digits


def _org_in(org: str | None, lower: str) -> bool:
    if not org:
        return True  # nothing claimed, nothing to check
    words = [w for w in re.findall(r"[a-z0-9]+", org.lower()) if len(w) >= 3 and w not in _GENERIC]
    return any(re.search(rf"\b{re.escape(w)}\b", lower) for w in words)
