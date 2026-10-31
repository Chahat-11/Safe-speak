"""Pure pattern matching: no ADK imports, so CrewAI's separate venv can use it too."""

import re

from safespeak.agents.pattern_catalogue import OFFICIAL_LINK, PATTERNS, ScamPattern
from safespeak.schemas import PatternMatch

SUPPORTING_BONUS = 0.05  # each supporting cue adds this much weight (capped at 1.0)
_SENTENCE_BREAK = re.compile(r"[.!?](?=\s|$)|\n")


def match_patterns(text: str) -> list[PatternMatch]:
    """All catalogue patterns whose required cues are present, strongest first."""
    text = OFFICIAL_LINK.sub("[official site]", text)
    matches = [m for p in PATTERNS if (m := _match(p, text))]
    return sorted(matches, key=lambda m: m.weight, reverse=True)


def _match(pattern: ScamPattern, text: str) -> PatternMatch | None:
    for name, cue in pattern.required.items():
        if not _cue_present(cue, text, pattern.exempt):
            return None
    supporting = [name for name, cue in pattern.supporting.items() if cue.search(text)]
    return PatternMatch(
        pattern_id=pattern.id,
        pattern_name=pattern.name,
        matched_cues=[*pattern.required, *supporting],
        weight=round(min(1.0, pattern.weight + SUPPORTING_BONUS * len(supporting)), 2),
    )


def _cue_present(cue, text: str, exempt) -> bool:
    """True if the cue appears in at least one sentence that is not exempt."""
    for hit in cue.finditer(text):
        if exempt is None or not exempt.search(_sentence_around(text, hit.start())):
            return True
    return False


def _sentence_around(text: str, index: int) -> str:
    """The whole sentence containing position `index`.

    A sentence ends at . ! ? followed by a space (or at a newline), so
    "Rs 1,500.00" and "amazon.in" do not split a sentence.
    """
    starts = [m.end() for m in _SENTENCE_BREAK.finditer(text, 0, index)]
    end = _SENTENCE_BREAK.search(text, index)
    return text[starts[-1] if starts else 0 : end.start() if end else len(text)]
