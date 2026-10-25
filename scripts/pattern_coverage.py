"""Development check for the Pattern specialist (no LLM, runs in seconds).

  python scripts/pattern_coverage.py                       # dev + hard negatives
  python scripts/pattern_coverage.py --show-misses 5

For each file: share of scam messages with >=1 pattern match (recall proxy)
and share of legitimate messages with a match (false-alarm proxy), per
archetype. These are DEVELOPMENT numbers on synthetic data, not results.
test_real.csv is refused: it must never be used for tuning.
"""

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from safespeak.agents.pattern import match_patterns  # noqa: E402
from safespeak.guardrails.redaction import redact  # noqa: E402

DEV_FILES = [Path("data/dev_synthetic.csv"), Path("data/hard_negatives_synthetic.csv")]


def coverage(path: Path, show_misses: int) -> None:
    if "test_real" in path.name:
        sys.exit("Refusing test_real.csv: it is the held-out reporting set. Use dev files.")
    by_arch: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])  # [hit, total]
    misses, false_alarms = [], []
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            text = redact(row["message_text"])[0]  # same text the agent sees
            matches = match_patterns(text)
            stats = by_arch[(row["label"], row["archetype"])]
            stats[1] += 1
            stats[0] += bool(matches)
            if row["label"] == "scam" and not matches:
                misses.append(text)
            if row["label"] == "legitimate" and matches:
                false_alarms.append((matches[0].pattern_id, text))

    print(f"\n== {path.name}")
    for label in ("scam", "legitimate"):
        rows = {a: s for (l, a), s in by_arch.items() if l == label}
        if not rows:
            continue
        hit, total = map(sum, zip(*rows.values()))
        what = "flagged (want high)" if label == "scam" else "false alarms (want low)"
        print(f"{label}: {hit}/{total} = {hit / total:.1%} {what}")
        for arch, (h, t) in sorted(rows.items()):
            print(f"    {arch:<42} {h:>4}/{t:<4} {h / t:6.1%}")
    for text in misses[:show_misses]:
        print(f"  MISS: {text[:160]}")
    for pid, text in false_alarms[:show_misses]:
        print(f"  FALSE ALARM [{pid}]: {text[:160]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="*", type=Path, default=DEV_FILES)
    parser.add_argument("--show-misses", type=int, default=0)
    args = parser.parse_args()
    for path in args.files:
        coverage(path, args.show_misses)


if __name__ == "__main__":
    main()
