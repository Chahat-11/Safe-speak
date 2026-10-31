"""Evaluation harness on a tiny CSV, with the fake LLM."""

import csv

from safespeak.evaluate import (
    AGENT_COLUMNS, MESSAGE_COLUMNS, evaluate, read_rows, sample_rows, summary, write_csv,
)
from tests.fake_llm import APPROVED, EXPLANATION, PARSED, TOOL_CALLS, VERDICT, FakeLlm


def _csv(path, rows):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["message_text", "label", "archetype"])
        w.writeheader()
        w.writerows(rows)


async def test_harness_writes_message_and_agent_rows(tmp_path):
    data = tmp_path / "mini.csv"
    _csv(data, [
        {"message_text": "KYC pending, click http://hdfc-kyc-update.in", "label": "scam", "archetype": "kyc"},
        {"message_text": "   ", "label": "legitimate", "archetype": "empty"},
    ])
    llm = FakeLlm(script={"parser": [PARSED], "verifier": [TOOL_CALLS, "done"], "reasoner": [VERDICT],
                          "explainer": [EXPLANATION], "critic": [APPROVED]}, requests=[])

    messages, agents = await evaluate(data, n=2, seed=0, model=llm)

    scam = next(m for m in messages if m["label"] == "scam")
    assert scam["predicted"] == "scam" and scam["correct"] is True
    assert any(a["agent"] == "reasoner" and a["prompt_tokens"] == 100 for a in agents)
    assert "message_text" not in MESSAGE_COLUMNS  # never written to results
    assert "accuracy: 100.0%" in summary(messages)

    write_csv(tmp_path / "m.csv", MESSAGE_COLUMNS, messages)
    write_csv(tmp_path / "a.csv", AGENT_COLUMNS, agents)
    assert len((tmp_path / "a.csv").read_text().splitlines()) == len(agents) + 1


async def test_resume_skips_finished_rows_and_saves_as_it_goes(tmp_path):
    data = tmp_path / "mini.csv"
    _csv(data, [{"message_text": "   ", "label": "scam", "archetype": "a"},
                {"message_text": "  ", "label": "legitimate", "archetype": "b"}])
    stem = tmp_path / "run"
    first, _ = await evaluate(data, n=2, seed=0, model=FakeLlm(script={}, requests=[]), run_stem=stem)
    second, _ = await evaluate(data, n=2, seed=0, model=FakeLlm(script={}, requests=[]), run_stem=stem)

    assert len(first) == 2 and len(second) == 2  # nothing ran twice
    assert len(read_rows(tmp_path / "run_messages.csv")) == 2


def test_sample_keeps_label_balance_and_is_repeatable(tmp_path):
    data = tmp_path / "mini.csv"
    _csv(data, [{"message_text": str(i), "label": "scam" if i < 30 else "legitimate", "archetype": "a"} for i in range(40)])
    sample = sample_rows(data, 20, 1)
    assert sum(r["label"] == "scam" for _, r in sample) == 15
    assert sample == sample_rows(data, 20, 1)
