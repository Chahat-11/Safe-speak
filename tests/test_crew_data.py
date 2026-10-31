"""The plain-code half of the crews. Runs in the main venv: no CrewAI, no LLM."""

import csv
import json

import pytest

from safespeak.crews.data import measure, missed_scams, proposal_matches, summarise_trace
from safespeak.schemas import PatternProposal

PROPOSAL = PatternProposal(name="x", tactic="y", cue_groups=[["scratch card", "voucher"], ["contact us"]])


def _csv(path, rows):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["message_text", "label"])
        w.writeheader()
        w.writerows(rows)
    return path


def test_crews_refuse_the_held_out_test_set(tmp_path):
    path = _csv(tmp_path / "test_real.csv", [{"message_text": "hi", "label": "scam"}])
    with pytest.raises(ValueError):
        missed_scams(5, path=path)


def test_missed_scams_excludes_what_the_catalogue_catches_and_masks_secrets(tmp_path):
    path = _csv(tmp_path / "dev.csv", [
        {"message_text": "You won a lottery! Pay Rs 500 fee to claim.", "label": "scam"},
        {"message_text": "Your interview passed, OTP 482913, contact us.", "label": "scam"},
        {"message_text": "Delivered today.", "label": "legitimate"},
    ])
    assert missed_scams(5, path=path).messages == ["Your interview passed, OTP [OTP], contact us."]


def test_every_group_must_match():
    assert proposal_matches(PROPOSAL, "Your voucher is ready, contact us now")
    assert not proposal_matches(PROPOSAL, "Your voucher is ready")


def test_measure_counts_hits_and_false_alarms(tmp_path):
    dev = _csv(tmp_path / "dev.csv", [
        {"message_text": "Scratch card won, contact us", "label": "scam"},
        {"message_text": "Pay now", "label": "scam"},
        {"message_text": "Voucher sent, contact us for help", "label": "legitimate"},
    ])
    neg = _csv(tmp_path / "neg.csv", [{"message_text": "Bill due", "label": "legitimate"}])
    e = measure(PROPOSAL, dev, neg)
    assert (e.scam_hits, e.scam_total, e.false_alarms, e.legit_total) == (1, 2, 1, 2)


def test_trace_summary_is_numbers_only(tmp_path):
    secret = "quoted message text"
    records = [
        {"kind": "agent", "name": "coordinator", "output": {"guardrail_events": [{"stage": "input", "action": "redacted", "reason": secret}]}},
        {"kind": "run", "metrics": {"agents": [{"agent": "parser", "calls": 2, "duration_ms": 100.0, "prompt_tokens": 30, "completion_tokens": 10}]}},
    ]
    path = tmp_path / "trace.jsonl"
    path.write_text("\n".join(map(json.dumps, records)))
    summary = summarise_trace(path)
    assert summary.runs == 1 and summary.guardrail_counts == {"input:redacted": 1}
    assert summary.agents[0].mean_duration_ms == 50.0 and summary.agents[0].mean_tokens == 20.0
    assert secret not in summary.model_dump_json()
