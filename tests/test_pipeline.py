"""End-to-end runs of the live ADK pipeline: fake LLM, real MCP server subprocess."""

import json

import pytest

from safespeak.agents.coordinator import SchemaViolation
from safespeak.app import analyse
from safespeak.schemas import CaseStatus, CheckResult, VerdictLabel
from tests.fake_llm import (
    APPROVED, DOMAIN, EXPLANATION, NEEDS_MORE, PARSED, REJECTED, TOOL_CALLS, VERDICT, FakeLlm,
)

MESSAGE = f"HDFC: Aapka KYC pending hai. OTP 482913 bhejo aaj hi http://{DOMAIN}/verify"


def fake(**overrides) -> FakeLlm:
    """Default script for a clean run; override any role's replies."""
    script = {
        "parser": [PARSED],
        "verifier": [TOOL_CALLS, "done"] * 3,
        "reasoner": [VERDICT],
        "explainer": [EXPLANATION],
        "critic": [APPROVED],
    }
    return FakeLlm(script={**script, **overrides}, requests=[])


async def test_happy_path_renders_markdown_and_closes_case():
    result = await analyse(MESSAGE, model=fake())

    assert result.case.status == CaseStatus.CLOSED
    assert result.case.verdict.label == VerdictLabel.SCAM
    assert result.case.critique.approved
    assert result.markdown.startswith("## ⚠️ This is a scam")
    assert "**Confidence:** 93%" in result.markdown


async def test_verifier_writes_real_findings_from_mcp_tools():
    result = await analyse(MESSAGE, model=fake())

    findings = {f.check: f for f in result.case.verifier_findings}
    assert findings["domain_age"].result == CheckResult.SUSPICIOUS  # registered 10 days ago
    assert findings["domain_age"].source_tool == "domain_age"
    assert findings["reputation"].result == CheckResult.SUSPICIOUS  # 'hdfc' lookalike
    assert all(f.indicator == DOMAIN for f in result.case.verifier_findings)


async def test_skipped_tool_call_becomes_unknown_finding():
    only_age = {"__calls__": [TOOL_CALLS["__calls__"][0]]}
    result = await analyse(MESSAGE, model=fake(verifier=[only_age, "done"]))

    findings = {f.check: f for f in result.case.verifier_findings}
    assert findings["reputation"].result == CheckResult.UNKNOWN
    assert any("skipped" in e.reason for e in result.case.guardrail_events)


async def test_tool_call_for_domain_not_in_message_is_ignored():
    stray = {"__calls__": [{"name": "domain_age", "args": {"indicator": "hdfcbank.com"}}]}
    result = await analyse(MESSAGE, model=fake(verifier=[stray, TOOL_CALLS, "done"]))

    assert {f.indicator for f in result.case.verifier_findings} == {DOMAIN}
    assert any("not in the message" in e.reason for e in result.case.guardrail_events)


async def test_raw_otp_never_reaches_llm_or_case():
    llm = fake()
    result = await analyse(MESSAGE, model=llm)

    assert "482913" not in result.case.message_text
    for request in llm.requests:
        assert "482913" not in str(request.config.system_instruction)
        assert "482913" not in str(request.contents)


async def test_output_guard_drops_advice_to_share_otp():
    result = await analyse(MESSAGE, model=fake())

    assert "Share the OTP" not in result.markdown
    assert any(e.stage == "output" and e.action == "replaced" for e in result.case.guardrail_events)


async def test_invalid_output_is_retried_once_and_logged():
    result = await analyse(MESSAGE, model=fake(parser=["not json", PARSED]))

    retried = [e for e in result.case.guardrail_events if e.action == "retried"]
    assert len(retried) == 1 and "parser" in retried[0].reason
    assert result.case.status == CaseStatus.CLOSED


async def test_second_invalid_output_raises():
    with pytest.raises(SchemaViolation):
        await analyse(MESSAGE, model=fake(parser=["not json", {"channel": "pigeon"}]))


async def test_reasoner_loop_is_capped_at_two():
    llm = fake(reasoner=[NEEDS_MORE] * 3)
    result = await analyse(MESSAGE, model=llm)

    assert len(llm.calls_for("reasoner")) == 3  # first pass + 2 loop-backs
    assert result.case.reasoner_loops == 2
    assert "reasoner" in result.case.capped_loops
    assert result.case.verdict.needs_more_evidence  # the record stays truthful
    assert result.case.routing.specialists == ["verifier"]  # loop-back routed as requested


async def test_critic_rejection_sends_issues_back_to_explainer():
    llm = fake(critic=[REJECTED, APPROVED], explainer=[EXPLANATION, EXPLANATION])
    result = await analyse(MESSAGE, model=llm)

    second_explainer_prompt = str(llm.calls_for("explainer")[1].config.system_instruction)
    assert "Headline should mention the fake link." in second_explainer_prompt
    assert result.case.critique.approved and result.case.critic_loops == 1


async def test_critic_loop_is_capped_at_two():
    llm = fake(critic=[REJECTED] * 3, explainer=[EXPLANATION] * 3)
    result = await analyse(MESSAGE, model=llm)

    assert len(llm.calls_for("explainer")) == 3  # first draft + 2 rewrites
    assert result.case.critic_loops == 2
    assert "critic" in result.case.capped_loops
    assert result.case.status == CaseStatus.CLOSED  # still answers the user


async def test_empty_input_is_blocked_before_any_agent():
    llm = fake()
    result = await analyse("   ", model=llm)

    assert result.case is None
    assert "could not analyse" in result.markdown
    assert llm.requests == []


async def test_trace_has_agent_model_and_tool_records(trace_file):
    result = await analyse(MESSAGE, model=fake())

    records = [json.loads(line) for line in trace_file.read_text().splitlines()]
    kinds = {(r["kind"], r["name"]) for r in records if r["kind"] != "run"}
    assert {("model", "parser"), ("agent", "coordinator"), ("tool", "domain_age"), ("tool", "domain_reputation")} <= kinds
    assert records[-1]["kind"] == "run"

    by_agent = {m.agent: m for m in result.metrics.agents}
    assert by_agent["verifier"].model_calls == 2  # tool-call turn + final turn
    assert by_agent["parser"].duration_ms > 0
