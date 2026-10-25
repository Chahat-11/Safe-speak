"""Evaluation harness on a tiny CSV, with the fake LLM."""

import csv

from safespeak.evaluate import AGENT_COLUMNS, MESSAGE_COLUMNS, evaluate, summary, write_csv
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
