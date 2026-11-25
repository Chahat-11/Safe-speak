#!/bin/sh
# Rebuild docs/evaluation.md and docs/figures/ from every finished reporting run,
# then commit and push them. Safe to run any time: unfinished runs are left out
# of the tables (the figures show finished rows, with n in each title).
cd "$(dirname "$0")/.."
STEMS=$(.venv/bin/python - <<'PY'
import csv, pathlib
want = [("test_real", a, 40) for a in ("hierarchical", "sequential", "parallel")] + [("test_real", "hierarchical", 463), ("hard_negatives_synthetic", "hierarchical", 100)]
for f, a, n in want:
    p = pathlib.Path(f"results/{f}_{a}_n{n}_seed0_messages.csv")
    if p.exists() and sum(1 for r in csv.DictReader(p.open()) if not r["error"]) == n:
        print(f"results/{f}_{a}_n{n}_seed0")
PY
)
COMMIT=$(.venv/bin/python -c "import json,pathlib; print(json.loads(pathlib.Path('results/test_real_hierarchical_n40_seed0_manifest.json').read_text())['commit'])")
.venv/bin/python scripts/make_figures.py >/dev/null
{
  echo "# SafeSpeak evaluation"
  echo
  echo "Model: \`qwen2.5:3b\` on local Ollama, temperature 0. Code: commit \`$COMMIT\`."
  echo "Headline numbers come only from \`data/test_real.csv\` (463 real messages, never used for tuning)."
  echo "Hard negatives (synthetic, all legitimate) are a separate robustness check, never merged into the headline."
  echo "Scam is the positive class; a verdict of scam or suspicious counts as flagged; uncertain counts as not flagged."
  echo "The three n40 runs use the same 40 messages, so they compare the architectures directly."
  echo "Tables list finished runs only. Regenerate with \`scripts/publish_evaluation.sh\`."
  echo
  echo "## Figures"
  echo
  echo "Made by \`scripts/make_figures.py\` from finished rows only (n is in each title)."
  echo
  echo "![Time and tokens per message](figures/latency_boxplot.png)"
  echo
  echo "![Seconds per agent, by architecture](figures/agent_heatmap_architectures.png)"
  echo
  echo "![Seconds per agent, message by message](figures/agent_heatmap_messages.png)"
  echo
  .venv/bin/python -W ignore -m safespeak.report $STEMS --out /dev/stdout
} > docs/evaluation.md.tmp && mv docs/evaluation.md.tmp docs/evaluation.md
git add docs/evaluation.md docs/figures
git diff --cached --quiet && { echo "nothing new"; exit 0; }
git commit -q -m "Update evaluation report and figures

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git push -q origin main && echo "pushed $(date)"
