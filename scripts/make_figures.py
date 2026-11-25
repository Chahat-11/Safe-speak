"""Evaluation figures from the results CSVs: latency boxplots and agent heatmaps.

  .venv/bin/python scripts/make_figures.py      -> docs/figures/*.png

Only real, finished rows are plotted (errored rows are skipped), and every
title says how many messages it covers, so a half-finished run is labelled
as such. No message text is read: results CSVs never contain it.
"""

from __future__ import annotations

import csv
import statistics
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no window, just files
import matplotlib.pyplot as plt  # noqa: E402

RESULTS = Path("results")
OUT = Path("docs/figures")
# The pipeline in order; the coordinator is left out because its time is the sum of the others.
AGENTS = ["parser", "router", "verifier", "pattern", "retrieval", "correlation", "reasoner", "explainer", "critic"]
COMPARISON = ["hierarchical", "sequential", "parallel"]


def read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def finished_rows(stem: str) -> list[dict]:
    """Messages that ran to the end (an error row has no verdict or timing worth plotting)."""
    return [row for row in read(RESULTS / f"{stem}_messages.csv") if not row["error"]]


def agent_rows(stem: str, keep: set[str]) -> list[dict]:
    return [row for row in read(RESULTS / f"{stem}_agents.csv") if row["row"] in keep]


def latency_boxplot(runs: dict[str, list[dict]]) -> Path:
    """Seconds per message and tokens per message, one box per run."""
    labels = [f"{name}\n(n={len(rows)})" for name, rows in runs.items()]
    seconds = [[float(r["wall_ms"]) / 1000 for r in rows] for rows in runs.values()]
    tokens = [[int(r["total_tokens"]) for r in rows] for rows in runs.values()]

    fig, (left, right) = plt.subplots(1, 2, figsize=(12, 5))
    for axis, data, title, unit in ((left, seconds, "Time per message", "seconds"),
                                    (right, tokens, "Tokens per message", "tokens (prompt + reply)")):
        axis.boxplot(data, tick_labels=labels, showmeans=True)
        axis.set_title(title)
        axis.set_ylabel(unit)
        axis.grid(axis="y", alpha=0.3)
    fig.suptitle("SafeSpeak end-to-end cost per message (test_real, qwen2.5:3b on a local M1)")
    fig.tight_layout()
    return save(fig, "latency_boxplot.png")


def architecture_heatmap(runs: dict[str, list[dict]]) -> Path:
    """Mean seconds each agent spends per message, for each architecture."""
    matrix = []
    for name, rows in runs.items():
        per_agent = agent_rows(name_to_stem(name), {r["row"] for r in rows})
        matrix.append([_mean_seconds(per_agent, agent, len(rows)) for agent in AGENTS])
    columns = list(runs)
    return heatmap(
        values=[list(col) for col in zip(*matrix)],  # rows = agents, columns = runs
        row_labels=AGENTS, col_labels=[f"{c}\n(n={len(runs[c])})" for c in columns],
        title="Mean seconds per message spent in each agent",
        name="agent_heatmap_architectures.png", width=8,
    )


def message_heatmap(name: str, rows: list[dict]) -> Path:
    """Seconds per agent for every message of one run: where the time goes, message by message."""
    per_agent = agent_rows(name_to_stem(name), {r["row"] for r in rows})
    seconds = {(a["row"], a["agent"]): float(a["duration_ms"]) / 1000 for a in per_agent}
    order = [r["row"] for r in rows]
    values = [[seconds.get((row, agent), 0.0) for row in order] for agent in AGENTS]
    return heatmap(
        values=values, row_labels=AGENTS, col_labels=[str(i + 1) for i in range(len(order))],
        title=f"Seconds per agent for each message ({name}, n={len(order)}; 0 = agent did not run)",
        name="agent_heatmap_messages.png", width=max(10, len(order) * 0.3), annotate=False,
    )


def heatmap(values, row_labels, col_labels, title, name, width, annotate=True) -> Path:
    fig, axis = plt.subplots(figsize=(width, 5))
    image = axis.imshow(values, cmap="YlOrRd", aspect="auto")
    axis.set_xticks(range(len(col_labels)), col_labels, fontsize=8)
    axis.set_yticks(range(len(row_labels)), row_labels)
    if annotate:
        for i, row in enumerate(values):
            for j, value in enumerate(row):
                axis.text(j, i, f"{value:.1f}", ha="center", va="center", fontsize=9)
    fig.colorbar(image, ax=axis, label="seconds")
    axis.set_title(title)
    fig.tight_layout()
    return save(fig, name)


def _mean_seconds(per_agent: list[dict], agent: str, messages: int) -> float:
    """Average over ALL messages, counting 0 when the agent was not routed to."""
    total = sum(float(a["duration_ms"]) for a in per_agent if a["agent"] == agent)
    return total / 1000 / messages if messages else 0.0


def name_to_stem(name: str) -> str:
    return STEMS[name]


def save(fig, name: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


STEMS = {
    **{arch: f"test_real_{arch}_n40_seed0" for arch in COMPARISON},
    "full test set": "test_real_hierarchical_n463_seed0",
    "hard negatives": "hard_negatives_synthetic_hierarchical_n100_seed0",
}


def main() -> None:
    runs = {name: finished_rows(stem) for name, stem in STEMS.items()}
    runs = {name: rows for name, rows in runs.items() if rows}
    if not runs:
        sys.exit("No finished results yet: run scripts/run_benchmark.sh first.")
    comparison = {name: runs[name] for name in COMPARISON if name in runs}
    made = [latency_boxplot(runs), architecture_heatmap(comparison), message_heatmap("hierarchical", runs["hierarchical"])]
    for path in made:
        print(path)
    for name, rows in runs.items():
        seconds = [float(r["wall_ms"]) / 1000 for r in rows]
        print(f"{name}: n={len(rows)} median {statistics.median(seconds):.1f}s")


if __name__ == "__main__":
    main()
