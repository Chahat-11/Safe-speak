"""The monitor's stream, end to end: fake LLM, real pipeline, real MCP subprocess."""

import json

import pytest
from starlette.testclient import TestClient

from safespeak.ui import server
from tests.fake_llm import APPROVED, DOMAIN, EXPLANATION, PARSED, TOOL_CALLS, VERDICT, FakeLlm

MESSAGE = f"HDFC: KYC pending. OTP 482913 bhejo http://{DOMAIN}/verify"


@pytest.fixture
def client(monkeypatch):
    real = server.pipeline.analyse

    async def fake_analyse(text, architecture="hierarchical"):
        script = {"parser": [PARSED], "verifier": [TOOL_CALLS, "done"], "reasoner": [VERDICT],
                  "explainer": [EXPLANATION], "critic": [APPROVED]}
        return await real(text, model=FakeLlm(script=script, requests=[]), architecture=architecture)

    monkeypatch.setattr(server.pipeline, "analyse", fake_analyse)
    return TestClient(server.app)


def events(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def test_stream_shows_agents_tools_and_final_result_in_order(client):
    stream = events(client.post("/api/analyse", json={"text": MESSAGE}))
    names = [(e["event"], e.get("name")) for e in stream]

    assert names[0] == ("agent_start", "coordinator")
    assert ("agent_end", "parser") in names and ("agent_start", "critic") in names
    assert names.index(("agent_end", "parser")) < names.index(("agent_start", "reasoner"))
    assert any(e["event"] == "tool_end" and e["finding"]["check"] == "domain_age" for e in stream)
    assert any(e["event"] == "model_skipped" and e["guard"] == "stop_when_done" for e in stream)
    assert stream[-1]["event"] == "done" and stream[-1]["case"]["status"] == "closed"


def test_raw_otp_never_reaches_the_browser(client):
    response = client.post("/api/analyse", json={"text": MESSAGE})
    assert "482913" not in response.text and "[OTP]" in response.text


def test_blocked_message_reports_a_skipped_coordinator(client):
    stream = events(client.post("/api/analyse", json={"text": "   "}))
    assert any(e["event"] == "agent_skipped" and e["guard"] == "input_guardrail" for e in stream)
    assert stream[-1]["case"] is None and "could not analyse" in stream[-1]["markdown"]


def test_lock_is_released_so_a_second_run_works(client):
    assert client.post("/api/analyse", json={"text": "   "}).status_code == 200
    assert client.post("/api/analyse", json={"text": "   "}).status_code == 200


def test_unknown_architecture_is_rejected(client):
    assert client.post("/api/analyse", json={"text": "x", "architecture": "nope"}).status_code == 400
