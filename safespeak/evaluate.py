"""Minimal evaluation harness.

  python -m safespeak.evaluate --n 20                      # test_real.csv
  python -m safespeak.evaluate --file data/dev_synthetic.csv --n 50
  python -m safespeak.evaluate --n 40 --architecture sequential

Writes to results/ (message text is never written):
  <run>_messages.csv : one row per message (truth, prediction, latency, tokens)
  <run>_agents.csv   : one row per message x agent, from RunMetrics
  <run>_manifest.json: model, architecture, git commit, for reproducibility
<run> = <file>_<architecture>_n<n>_seed<seed>. Rows are saved as they finish
and a rerun of the same <run> resumes, so a long run survives interruption.
The sample keeps the file's scam/legitimate balance, so the same n and seed
give every architecture the same messages. Tables: python -m safespeak.report

Data rules (see CLAUDE.md): headline numbers come from test_real.csv only.
Never tune prompts or rules on it; iterate on dev_synthetic.csv instead.
Report hard_negatives_synthetic.csv separately.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import random
import statistics
import subprocess
import time
from datetime import datetime
from pathlib import Path

from safespeak import config
from safespeak.app import ARCHITECTURES, AnalysisResult, SafeSpeakService
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
    """(row number in file, row) pairs, stratified by label; same seed -> same sample."""
    with path.open(encoding="utf-8") as f:
        rows = list(enumerate(csv.DictReader(f), start=1))
    rng = random.Random(seed)
    rng.shuffle(rows)
    n = min(n, len(rows))
    labels = sorted({row["label"] for _, row in rows})
    chosen: list[tuple[int, dict]] = []
    for i, label in enumerate(labels):
        group = [item for item in rows if item[1]["label"] == label]
        last = i == len(labels) - 1
        take = n - len(chosen) if last else round(n * len(group) / len(rows))
        chosen.extend(group[:take])
    rng.shuffle(chosen)
    return chosen


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


async def evaluate(
    path: Path, n: int, seed: int, model=None, architecture: str = "hierarchical", run_stem: Path | None = None
) -> tuple[list[dict], list[dict]]:
    """Run the sample. With `run_stem`, save each row at once and skip finished ones."""
    messages = read_rows(_messages_path(run_stem)) if run_stem else []
    agents = read_rows(_agents_path(run_stem)) if run_stem else []
    finished = {int(m["row"]) for m in messages}
    sample = sample_rows(path, n, seed)
    async with SafeSpeakService(model, architecture) as service:
        for i, (row_no, truth) in enumerate(sample, start=1):
            if row_no in finished:
                continue
            result, error = None, ""
            start = time.perf_counter()
            try:
                result = await service.analyse(truth["message_text"])
            except Exception as err:  # one bad message must not stop the run
                error = f"{type(err).__name__}: {str(err).splitlines()[0][:150]}"
            wall_ms = (time.perf_counter() - start) * 1000
            row = message_row(row_no, truth, result, wall_ms, error)
            new_agents = agent_rows(row_no, result)
            messages.append(row)
            agents.extend(new_agents)
            if run_stem:
                append_csv(_messages_path(run_stem), MESSAGE_COLUMNS, [row])
                append_csv(_agents_path(run_stem), AGENT_COLUMNS, new_agents)
            print(f"[{i}/{len(sample)}] row {row_no}: {row.get('predicted', 'ERROR')} "
                  f"(truth {truth['label']}) {wall_ms / 1000:.1f}s", flush=True)
    return messages, agents


def _messages_path(stem: Path) -> Path:
    return stem.with_name(stem.name + "_messages.csv")


def _agents_path(stem: Path) -> Path:
    return stem.with_name(stem.name + "_agents.csv")


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        if is_new:
            writer.writeheader()
        writer.writerows(rows)


def write_manifest(stem: Path, args: argparse.Namespace) -> None:
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout.strip())
    manifest = {"file": str(args.file), "architecture": args.architecture, "n": args.n, "seed": args.seed,
                "model": config.MODEL, "commit": commit, "uncommitted_changes": dirty,
                "started": datetime.now().isoformat(timespec="seconds")}
    stem.with_name(stem.name + "_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def summary(messages: list[dict]) -> str:
    done = [m for m in messages if not m["error"] and m.get("predicted")]
    if not done:
        return "No successful runs."
    correct = sum(str(m["correct"]) == "True" for m in done)
    uncertain = sum(m["predicted"] == "uncertain" for m in done)
    scams = [m for m in done if m["label"] == "scam"]
    flagged = [m for m in done if m["predicted"] == "scam"]
    caught = sum(m["label"] == "scam" for m in flagged)
    latency = [float(m["wall_ms"]) / 1000 for m in done]
    return "\n".join([
        f"messages: {len(messages)}  scored: {len(done)}  not scored (error or blocked): {len(messages) - len(done)}",
        f"accuracy: {correct / len(done):.1%}  (uncertain counted as wrong; {uncertain} uncertain)",
        f"scam recall: {caught}/{len(scams)}  scam precision: {caught}/{len(flagged)}",
        f"latency s: median {statistics.median(latency):.1f}  max {max(latency):.1f}",
        f"tokens/message: mean {statistics.mean(float(m['total_tokens']) for m in done):.0f}",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    parser.add_argument("--n", type=int, default=20)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--architecture", choices=list(ARCHITECTURES), default="hierarchical")
    args = parser.parse_args()

    stem = RESULTS_DIR / f"{args.file.stem}_{args.architecture}_n{args.n}_seed{args.seed}"
    RESULTS_DIR.mkdir(exist_ok=True)
    write_manifest(stem, args)
    messages, _ = asyncio.run(evaluate(args.file, args.n, args.seed, architecture=args.architecture, run_stem=stem))
    print("\n" + summary(messages))
    print(f"\nWrote {_messages_path(stem)} and {_agents_path(stem)}")


if __name__ == "__main__":
    main()
