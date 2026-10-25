"""Minimal evaluation harness.

  python -m safespeak.evaluate --n 20                      # test_real.csv
  python -m safespeak.evaluate --file data/dev_synthetic.csv --n 50

Writes two CSVs to results/ (message text is never written):
  <file>_<time>_messages.csv : one row per message (truth, prediction, latency, tokens)
  <file>_<time>_agents.csv   : one row per message x agent, from RunMetrics

Data rules (see CLAUDE.md): headline numbers come from test_real.csv only.
Never tune prompts or rules on it; iterate on dev_synthetic.csv instead.
Report hard_negatives_synthetic.csv separately.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import random
import statistics
import time
from datetime import datetime
from pathlib import Path

from safespeak.app import AnalysisResult, SafeSpeakService
from safespeak.schemas import VerdictLabel

DEFAULT_FILE = Path("data/test_real.csv")
RESULTS_DIR = Path("results")

# Our four labels -> the dataset's two. "uncertain" stays its own bucket.
TO_DATASET_LABEL = {
    VerdictLabel.SCAM: "scam",
    VerdictLabel.SUSPICIOUS: "scam",
    VerdictLabel.LIKELY_SAFE: "legitimate",
    VerdictLabel.UNCERTAIN: "uncertain",
}

MESSAGE_COLUMNS = [
    "row", "label", "archetype", "predicted", "predicted_raw", "correct", "confidence",
    "wall_ms", "total_tokens", "reasoner_loops", "critic_loops", "capped_loops",
    "verifier_findings", "guardrail_events", "error",
]
AGENT_COLUMNS = ["row", "agent", "calls", "duration_ms", "model_calls", "prompt_tokens", "completion_tokens"]


def sample_rows(path: Path, n: int, seed: int) -> list[tuple[int, dict]]:
    """(row number in file, row) pairs; same seed -> same sample."""
    with path.open(encoding="utf-8") as f:
        rows = list(enumerate(csv.DictReader(f), start=1))
    return random.Random(seed).sample(rows, min(n, len(rows)))


def message_row(row_no: int, truth: dict, result: AnalysisResult | None, wall_ms: float, error: str) -> dict:
    out = {"row": row_no, "label": truth["label"], "archetype": truth["archetype"],
           "wall_ms": round(wall_ms), "error": error}
    case = result.case if result else None
    if case is None or case.verdict is None:
        return out
    predicted = TO_DATASET_LABEL[case.verdict.label]
    out.update(
        predicted=predicted,
        predicted_raw=case.verdict.label.value,
        correct=predicted == truth["label"],
        confidence=case.verdict.confidence,
        total_tokens=result.metrics.total_tokens,
        reasoner_loops=case.reasoner_loops,
        critic_loops=case.critic_loops,
        capped_loops="|".join(case.capped_loops),
        verifier_findings=len(case.verifier_findings),
        guardrail_events=len(case.guardrail_events),
    )
    return out


def agent_rows(row_no: int, result: AnalysisResult | None) -> list[dict]:
    if result is None:
        return []
    return [{"row": row_no, **m.model_dump()} for m in result.metrics.agents]


async def evaluate(path: Path, n: int, seed: int, model=None) -> tuple[list[dict], list[dict]]:
    messages, agents = [], []
    async with SafeSpeakService(model) as service:
        for i, (row_no, truth) in enumerate(sample_rows(path, n, seed), start=1):
            result, error = None, ""
            start = time.perf_counter()
            try:
                result = await service.analyse(truth["message_text"])
            except Exception as err:  # one bad message must not stop the run
                error = f"{type(err).__name__}: {str(err).splitlines()[0][:150]}"
            wall_ms = (time.perf_counter() - start) * 1000
            messages.append(message_row(row_no, truth, result, wall_ms, error))
            agents.extend(agent_rows(row_no, result))
            print(f"[{i}/{n}] row {row_no}: {messages[-1].get('predicted', 'ERROR')} "
                  f"(truth {truth['label']}) {wall_ms / 1000:.1f}s")
    return messages, agents


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def summary(messages: list[dict]) -> str:
    done = [m for m in messages if not m["error"] and "predicted" in m]
    if not done:
        return "No successful runs."
    correct = sum(m["correct"] for m in done)
    uncertain = sum(m["predicted"] == "uncertain" for m in done)
    scams = [m for m in done if m["label"] == "scam"]
    flagged = [m for m in done if m["predicted"] == "scam"]
    caught = sum(m["label"] == "scam" for m in flagged)
    latency = [m["wall_ms"] / 1000 for m in done]
    return "\n".join([
        f"messages: {len(messages)}  scored: {len(done)}  not scored (error or blocked): {len(messages) - len(done)}",
        f"accuracy: {correct / len(done):.1%}  (uncertain counted as wrong; {uncertain} uncertain)",
        f"scam recall: {caught}/{len(scams)}  scam precision: {caught}/{len(flagged)}",
        f"latency s: median {statistics.median(latency):.1f}  max {max(latency):.1f}",
        f"tokens/message: mean {statistics.mean(m['total_tokens'] for m in done):.0f}",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    parser.add_argument("--n", type=int, default=20)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    messages, agents = asyncio.run(evaluate(args.file, args.n, args.seed))
    stem = f"{args.file.stem}_{datetime.now():%Y%m%d_%H%M%S}"
    write_csv(RESULTS_DIR / f"{stem}_messages.csv", MESSAGE_COLUMNS, messages)
    write_csv(RESULTS_DIR / f"{stem}_agents.csv", AGENT_COLUMNS, agents)
    print("\n" + summary(messages))
    print(f"\nWrote {RESULTS_DIR}/{stem}_messages.csv and _agents.csv")


if __name__ == "__main__":
    main()
