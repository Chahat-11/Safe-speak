"""Language guardrail: after_agent callback on the Parser.

The LLM's guess at `parsed.language` proved unreliable (qwen2.5:7b tagged
half of a sample of English messages as Hindi, and the Explainer then wrote
broken Hindi). Language is checked here in plain code instead:
  - Devanagari script                       -> "hi"
  - 2+ distinct common romanised Hindi words -> "hinglish"
    (after squeezing repeated letters, so "terii" counts as "teri")
  - otherwise                               -> "en"
If the Parser disagreed, the field is corrected and a GuardrailEvent logged.

check_explanation_script (after_agent on the Explainer): an English reply
must not contain Devanagari. If it does, it raises, so the Coordinator's
one-retry rule re-runs the Explainer instead of spending a Critic loop.
"""

import re

from google.adk.agents.callback_context import CallbackContext

from safespeak.blackboard import log_guardrail, post, read_case

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_HINGLISH_WORDS = {
    "hai", "hain", "aap", "aapka", "aapke", "apka", "apke", "karo", "kare", "kijiye", "karein",
    "nahi", "nahin", "kya", "mein", "bhejo", "jaldi", "abhi", "aaj", "paisa", "paise", "raha",
    "rahe", "gaya", "hoga", "wala", "wale", "batao", "mat", "kisi", "apna", "apni", "yeh", "lekin",
    "teri", "tera", "tere", "mera", "meri", "tum", "tumhara", "bhai", "yar", "kaise", "kyu", "kyun",
    "ki", "karna", "karke", "hua", "tha", "thi", "bohot", "bahut", "accha",
}


_HINGLISH_WORDS = {re.sub(r"(.)\1+", r"\1", w) for w in _HINGLISH_WORDS}  # squeezed like the text


REPLY_LANGUAGE = {
    "en": "English",
    "hi": "Hindi (Devanagari script)",
    "hinglish": "Hinglish (Hindi written in English letters)",
}


def detect_language(text: str) -> str:
    letters = [c for c in text if c.isalpha()]
    if letters and sum(bool(_DEVANAGARI.match(c)) for c in letters) / len(letters) > 0.3:
        return "hi"
    # Squeeze repeated letters so "terii" and "kiii" count as "teri" and "ki".
    words = set(re.findall(r"[a-z]+", re.sub(r"([a-z])\1+", r"\1", text.lower())))
    return "hinglish" if len(words & _HINGLISH_WORDS) >= 2 else "en"


def correct_language(callback_context: CallbackContext) -> None:
    state = callback_context.state
    case = read_case(state)
    if case.parsed is None:
        return
    detected = detect_language(case.message_text)
    if case.parsed.language != detected:
        post(state, "parsed", case.parsed.model_copy(update={"language": detected}))
        log_guardrail(state, "agent", "replaced", f"Parser said language {case.parsed.language!r}; text is {detected!r}.")


def check_explanation_script(callback_context: CallbackContext) -> None:
    case = read_case(callback_context.state)
    if case.parsed is None or case.explanation is None or case.parsed.language == "hi":
        return
    text = " ".join([case.explanation.headline, *case.explanation.why, *case.explanation.what_to_do])
    if _DEVANAGARI.search(text):
        raise ValueError(f"Explanation uses Devanagari but reply language is {case.parsed.language!r}")
