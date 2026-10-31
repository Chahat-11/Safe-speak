"""Turn results/*_messages.csv into performance tables (docs/evaluation.md).

  python -m safespeak.report results/test_real_hierarchical_n463_seed0 ...

Scam is the positive class. A verdict of scam or suspicious counts as flagged.
"uncertain" is not flagged, so an uncertain scam counts as missed; uncertain
is also reported on its own. Errors are counted, never silently dropped.
"""

from __future__ import annotations

import argparse
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from safespeak.evaluate import read_rows


@dataclass(frozen=True)
class Scores:
    n: int
    errors: int
    tp: int
    fp: int
    fn: int
    tn: int
    uncertain: int

    @property
    def scored(self) -> int:
        return self.tp + self.fp + self.fn + self.tn

    @property
    def accuracy(self) -> float:
        return _ratio(self.tp + self.tn, self.scored)

    @property
    def precision(self) -> float:
        return _ratio(self.tp, self.tp + self.fp)

    @property
    def recall(self) -> float:
        return _ratio(self.tp, self.tp + self.fn)

    @property
    def f1(self) -> float:
        return _ratio(2 * self.precision * self.recall, self.precision + self.recall)

    @property
    def false_alarm_rate(self) -> float:
        return _ratio(self.fp, self.fp + self.tn)


def _ratio(top: float, bottom: float) -> float:
    return top / bottom if bottom else 0.0


def score(rows: list[dict]) -> Scores:
    """Confusion counts. A legitimate message called uncertain is not a false alarm."""
    done = [r for r in rows if r.get("predicted")]
    is_scam = lambda r: r["label"] == "scam"  # noqa: E731
    flagged = lambda r: r["predicted"] == "scam"  # noqa: E731
    return Scores(
        n=len(rows),
        errors=len(rows) - len(done),
        tp=sum(is_scam(r) and flagged(r) for r in done),
        fp=sum(not is_scam(r) and flagged(r) for r in done),
        fn=sum(is_scam(r) and not flagged(r) for r in done),
        tn=sum(not is_scam(r) and not flagged(r) for r in done),
        uncertain=sum(r["predicted"] == "uncertain" for r in done),
    )


def wilson_95(successes: int, total: int) -> tuple[float, float]:
    """95% confidence interval for a proportion; honest about small samples."""
    if not total:
        return (0.0, 0.0)
    z, p = 1.96, successes / total
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return (max(0.0, centre - half), min(1.0, centre + half))


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1)] if ordered else 0.0


def overview_row(name: str, rows: list[dict]) -> str:
    s = score(rows)
    low, high = wilson_95(s.tp + s.tn, s.scored)
    done = [r for r in rows if r.get("predicted")]
    seconds = [float(r["wall_ms"]) / 1000 for r in done]
    tokens = [float(r["total_tokens"]) for r in done]
    return (
        f"| {name} | {s.scored}/{s.n} | {s.accuracy:.1%} ({low:.1%}–{high:.1%}) | {s.precision:.1%} | {s.recall:.1%} "
        f"| {s.f1:.3f} | {s.false_alarm_rate:.1%} | {s.uncertain} | {s.errors} "
        f"| {_mean(seconds):.1f} | {percentile(seconds, 0.5):.1f} | {percentile(seconds, 0.95):.1f} | {_mean(tokens):.0f} |"
    )


def _mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


OVERVIEW_HEADER = (
    "| Run | Scored | Accuracy (95% CI) | Precision | Recall | F1 | False alarms | Uncertain | Errors "
    "| Mean s | p50 s | p95 s | Tokens/msg |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|"
)


def agent_table(rows: list[dict], messages: int) -> list[str]:
    """Mean cost per message by agent. Coordinator time includes its sub-agents."""
    totals: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    for r in rows:
        t = totals[r["agent"]]
        t[0] += float(r["duration_ms"])
        t[1] += float(r["model_calls"])
        t[2] += float(r["prompt_tokens"]) + float(r["completion_tokens"])
    lines = ["| Agent | ms/message | LLM calls/message | Tokens/message |", "|---|---|---|---|"]
    for agent, (ms, calls, tokens) in sorted(totals.items(), key=lambda kv: -kv[1][0]):
        lines.append(f"| {agent} | {ms / messages:.0f} | {calls / messages:.2f} | {tokens / messages:.0f} |")
    return lines


def archetype_table(rows: list[dict]) -> list[str]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r["archetype"]].append(r)
    lines = ["| Archetype | Messages | Correct | Accuracy |", "|---|---|---|---|"]
    for name, items in sorted(groups.items()):
        s = score(items)
        lines.append(f"| {name} | {s.n} | {s.tp + s.tn} | {s.accuracy:.1%} |")
    return lines


def build_report(stems: list[Path]) -> str:
    out = ["## Overview", "", OVERVIEW_HEADER]
    for stem in stems:
        out.append(overview_row(stem.name, read_rows(stem.with_name(stem.name + "_messages.csv"))))
    for stem in stems:
        messages = read_rows(stem.with_name(stem.name + "_messages.csv"))
        agents = read_rows(stem.with_name(stem.name + "_agents.csv"))
        out += ["", f"## {stem.name}", "", *agent_table(agents, max(len(messages), 1)), "", *archetype_table(messages)]
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stems", nargs="+", type=Path, help="run names without _messages.csv")
    parser.add_argument("--out", type=Path, help="also write the Markdown here")
    args = parser.parse_args()
    report = build_report(args.stems)
    print(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
