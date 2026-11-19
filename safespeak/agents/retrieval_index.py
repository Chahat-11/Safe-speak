"""Past-case search for the Retrieval specialist. Pure Python, no ADK.

The "knowledge base" is the labelled development set (data/dev_synthetic.csv):
2737 known scam and legitimate messages. A new message is compared with all
of them by TF-IDF cosine similarity over words and word pairs; the closest
ones above MIN_SIMILARITY come back as RetrievedEvidence.

Why TF-IDF and not embeddings: no extra model or library, runs in
milliseconds on an 8 GB laptop, and the score is easy to explain.
Why dev only: test_real.csv is never indexed (it would leak the answers),
and the hard negatives are kept out so they stay an independent check.
MIN_SIMILARITY = 0.3 was chosen on dev + hard negatives. Realistic scams
score about 0.3 against the synthetic set, so 0.4 would rarely fire. At 0.3,
79 of 3433 legitimate hard negatives (2.3%) had mostly-scam neighbours, so
the Reasoner treats retrieval as supporting evidence only, never a sign that
decides a label on its own (see the Reasoner prompt).
"""

from __future__ import annotations

import csv
import math
import re
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from safespeak import config
from safespeak.guardrails.redaction import redact
from safespeak.schemas import RetrievedEvidence

MIN_SIMILARITY = 0.3
TOP_K = 3
SNIPPET_CHARS = 160


def search(text: str, k: int = TOP_K, min_similarity: float = MIN_SIMILARITY) -> list[RetrievedEvidence]:
    """The k most similar known cases, most similar first."""
    index = _index(config.RETRIEVAL_CORPUS)
    scores: dict[int, float] = defaultdict(float)
    for term, weight in index.vector(text).items():
        for doc, doc_weight in index.postings.get(term, []):
            scores[doc] += weight * doc_weight
    best = sorted(scores.items(), key=lambda item: -item[1])[:k]
    return [index.evidence(doc, score) for doc, score in best if score >= min_similarity]


def _tokens(text: str) -> list[str]:
    """Words (and masked placeholders like [otp]) plus each adjacent word pair."""
    words = re.findall(r"\[[a-z]+\]|[a-z0-9]+", text.lower())
    return words + [f"{a}_{b}" for a, b in zip(words, words[1:])]


class _Index:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        counts = [Counter(_tokens(redact(r["message_text"])[0])) for r in rows]
        df = Counter(term for c in counts for term in c)
        self.idf = {t: math.log((1 + len(rows)) / (1 + n)) + 1 for t, n in df.items()}
        self.postings: dict[str, list[tuple[int, float]]] = defaultdict(list)
        for doc, c in enumerate(counts):
            for term, weight in self._normalise(c).items():
                self.postings[term].append((doc, weight))

    def vector(self, text: str) -> dict[str, float]:
        return self._normalise(Counter(_tokens(text)))

    def _normalise(self, counts: Counter) -> dict[str, float]:
        weights = {t: (1 + math.log(n)) * self.idf[t] for t, n in counts.items() if t in self.idf}
        norm = math.sqrt(sum(w * w for w in weights.values())) or 1.0
        return {t: w / norm for t, w in weights.items()}

    def evidence(self, doc: int, score: float) -> RetrievedEvidence:
        row = self.rows[doc]
        return RetrievedEvidence(
            source_id=f"dev_synthetic:{doc + 2}",  # CSV line number, header is line 1
            title=f"Known {row['label']} message ({row['archetype']})",
            snippet=redact(row["message_text"])[0][:SNIPPET_CHARS],
            similarity=round(min(score, 1.0), 3),
            source="dev_synthetic",
        )


@lru_cache(maxsize=2)
def _index(path: Path) -> _Index:
    if "test_real" in Path(path).name:
        raise ValueError("test_real.csv must never be indexed: it is the held-out test set.")
    with Path(path).open(newline="", encoding="utf-8") as f:
        return _Index(list(csv.DictReader(f)))
