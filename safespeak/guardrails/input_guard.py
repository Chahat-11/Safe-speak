"""Input guardrail: before_agent callback on the Coordinator.

Runs before any agent sees the message. It:
  1. blocks empty or oversized messages,
  2. masks secrets (OTP, card, account, Aadhaar) so raw values are never stored,
  3. flags prompt-injection phrases (logged, not blocked: scammers use them too,
     and agents only ever see the message as JSON data, never as instructions),
  4. flags abusive language (logged, not blocked: abuse is not a scam, but the
     record should show it was noticed).
The result is a GuardedInput in state; the Coordinator opens the case from it.
"""

import re

from google.adk.agents.callback_context import CallbackContext
from google.genai import types

from safespeak import config
from safespeak.guardrails.redaction import redact
from safespeak.schemas import GuardedInput, GuardrailEvent

GUARDED_INPUT_KEY = "guarded_input"

_INJECTION = re.compile(
    r"(?i)\b(?:ignore|disregard|forget|override|bypass)\s+(?:all|any|the|your|my|previous|prior|above|these|those)\b"
    r".{0,20}\b(?:instructions?|rules|prompt|above|guidelines)\b"
    r"|system prompt|you are now|^\s*(?:system|assistant)\s*:"
    r"|\b(?:mark|classify|label|treat|report|flag)\s+(?:this|it|the message|me)\s+as\s+(?:safe|legit\w*|genuine|not (?:a )?scam)"
)
# Common English and Hinglish abuse. Matched after squeezing repeated letters
# ("chooottt" -> "chot"), the usual way people dodge word filters.
_ABUSE = re.compile(
    r"\b(?:f[u*]ck\w*|bitch\w*|bastard|slut|whore|asshole|nig(?:a|ah|as)?|chutiy\w*|madarchod|bh?enchod"
    r"|bhosd\w*|gand|gandu|randi|harami|kamin[ae])\b|\bma+ ?ki+ ?cho?t"
)


def check_input(text: str) -> GuardedInput:
    """Pure function (easy to unit test): decide what happens to the raw text."""
    text = text.strip()
    if not text:
        return _blocked("Message is empty.")
    if len(text) > config.MAX_MESSAGE_CHARS:
        return _blocked(f"Message is longer than {config.MAX_MESSAGE_CHARS} characters.")

    masked, found = redact(text)
    events = [GuardrailEvent(stage="input", action="allowed", reason="Passed input checks.")]
    if found:
        events.append(_event("redacted", f"Masked: {', '.join(sorted(set(found)))}"))
    if _INJECTION.search(text):
        events.append(_event("flagged", "Contains prompt-injection phrasing."))
    if _ABUSE.search(_squeeze(text)):
        events.append(_event("flagged", "Contains abusive language."))
    return GuardedInput(text=masked, events=events)


def _squeeze(text: str) -> str:
    """Lower-case and collapse repeated letters: 'Chooottt' -> 'chot'."""
    return re.sub(r"(.)\1+", r"\1", text.lower())


def input_guardrail(callback_context: CallbackContext) -> types.Content | None:
    """ADK callback. Returning Content stops the run and becomes the reply."""
    guarded = check_input(_user_text(callback_context.user_content))
    callback_context.state[GUARDED_INPUT_KEY] = guarded.model_dump(mode="json")
    if guarded.blocked:
        reason = guarded.events[-1].reason
        return types.Content(role="model", parts=[types.Part(text=f"SafeSpeak could not analyse this: {reason}")])
    return None


def _user_text(content: types.Content | None) -> str:
    if content is None or not content.parts:
        return ""
    return "".join(part.text or "" for part in content.parts)


def _blocked(reason: str) -> GuardedInput:
    return GuardedInput(text="", blocked=True, events=[_event("blocked", reason)])


def _event(action: str, reason: str) -> GuardrailEvent:
    return GuardrailEvent(stage="input", action=action, reason=reason)
