"""Blackboard behaviour, tested against ADK's real State object."""

import pytest
from google.adk.sessions.state import State
from pydantic import ValidationError

from safespeak import blackboard as bb
from safespeak.schemas import (
    CaseStatus,
    Explanation,
    ParsedMessage,
    Verdict,
    VerdictLabel,
)


def new_state() -> State:
    return State(value={}, delta={})


def test_open_and_read_case():
    state = new_state()
    case = bb.open_case(state, "Your account is blocked, share OTP")
    assert bb.read_case(state).case_id == case.case_id
    assert bb.read_case(state).status == CaseStatus.OPEN


def test_write_is_recorded_as_state_delta():
    state = new_state()
    bb.open_case(state, "hi")
    assert bb.CASE_KEY in state._delta  # ADK will persist this


def test_post_section_and_status():
    state = new_state()
    bb.open_case(state, "hi")
    bb.post(state, "parsed", ParsedMessage(urls=["http://x.io"]), CaseStatus.PARSED)
    case = bb.read_case(state)
    assert case.parsed.urls == ["http://x.io"]
    assert case.status == CaseStatus.PARSED


def test_wrong_type_in_section_is_rejected():
    state = new_state()
    bb.open_case(state, "hi")
    wrong = Explanation(headline="h", why=["w"], what_to_do=["d"])
    with pytest.raises(ValidationError):
        bb.post(state, "verdict", wrong)


def test_identity_fields_are_read_only():
    state = new_state()
    bb.open_case(state, "hi")
    with pytest.raises(bb.BlackboardError):
        bb.post(state, "case_id", "hacked")


def test_loop_counter_and_guardrail_log():
    state = new_state()
    bb.open_case(state, "hi")
    assert bb.increment_loop(state, "reasoner_loops") == 1
    assert bb.increment_loop(state, "reasoner_loops") == 2
    bb.log_guardrail(state, "input", "redacted", "OTP masked")
    assert bb.read_case(state).guardrail_events[0].action == "redacted"


def test_verdict_confidence_bounds():
    with pytest.raises(ValidationError):
        Verdict(label=VerdictLabel.SCAM, confidence=1.5, key_reasons=["x"])
