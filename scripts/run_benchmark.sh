#!/bin/sh
# Reporting runs. Safe to rerun: each run resumes from its saved rows.
# Comparison: the same 40 test_real messages on each architecture.
# Then the full test set, then hard negatives (reported separately).
cd "$(dirname "$0")/.."
PY=".venv/bin/python -u -W ignore -m safespeak.evaluate"
for arch in hierarchical sequential parallel; do
  $PY --file data/test_real.csv --n 40 --seed 0 --architecture "$arch"
done
$PY --file data/test_real.csv --n 463 --seed 0
$PY --file data/hard_negatives_synthetic.csv --n 100 --seed 0
