"""End-to-end runs of the live ADK pipeline: fake LLM, real MCP server subprocess."""

import json

import pytest

from safespeak.agents.coordinator import SchemaViolation
from safespeak.app import analyse
from safespeak.schemas import CaseStatus, CheckResult, VerdictLabel
from tests.fake_llm import (
    APPROVED, DOMAIN, EXPLANATION, NEEDS_MORE, PARSED, REJECTED, SAYS_SAFE, HEDGED, INVENTS_NUMBER, TOOL_CALLS, VERDICT, FakeLlm,
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
    assert "credential_request" in {m.pattern_id for m in result.case.pattern_matches}  # "OTP bhejo"
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
    # The Verifier keeps skipping the reputation check, so every loop-back is
    # genuinely useful and only the cap can stop it.
    only_age = {"__calls__": [TOOL_CALLS["__calls__"][0]]}
    llm = fake(reasoner=[NEEDS_MORE] * 3, verifier=[only_age, "done"] * 3, explainer=[HEDGED])
    result = await analyse(MESSAGE, model=llm)

    assert len(llm.calls_for("reasoner")) == 3  # first pass + 2 loop-backs
    assert result.case.reasoner_loops == 2
    assert "reasoner" in result.case.capped_loops
    assert any("loop cap" in e.reason for e in result.case.guardrail_events)
    assert result.case.verdict.needs_more_evidence  # the record stays truthful
    assert result.case.routing.specialists == ["verifier"]  # loop-back routed as requested


async def test_confirmed_rejection_sends_issues_back_to_explainer():
    llm = fake(critic=[REJECTED, APPROVED], explainer=[SAYS_SAFE, EXPLANATION])
    result = await analyse(MESSAGE, model=llm)

    second_explainer_prompt = str(llm.calls_for("explainer")[1].config.system_instruction)
    assert "Headline says the message is safe" in second_explainer_prompt  # code's issue
    assert "The headline says it is safe but the verdict is scam." in second_explainer_prompt  # Critic's wording
    assert result.case.critique.approved and result.case.critic_loops == 1


async def test_unconfirmed_rejection_does_not_cost_a_rewrite():
    llm = fake(critic=[REJECTED])  # Critic objects, but the draft agrees with the verdict
    result = await analyse(MESSAGE, model=llm)

    assert len(llm.calls_for("explainer")) == 1
    assert result.case.critique.approved
    assert any("not confirmed" in e.reason for e in result.case.guardrail_events)


async def test_critic_unsupported_claim_is_confirmed_by_code():
    tagged = {"approved": False, "issues": ["[unsupported] There is no phone number in the message."]}
    llm = fake(critic=[tagged, APPROVED], explainer=[INVENTS_NUMBER, EXPLANATION])
    result = await analyse(MESSAGE, model=llm)

    second_explainer_prompt = str(llm.calls_for("explainer")[1].config.system_instruction)
    assert "message has none" in second_explainer_prompt
    assert "There is no phone number in the message." in second_explainer_prompt
    assert result.case.critique.approved


async def test_passed_checks_listed_as_issues_are_ignored():
    # the 3B Critic's habit: listing a check that passed
    noisy = {"approved": False, "issues": ["The explanation does not contradict the verdict."]}
    llm = fake(critic=[noisy])
    result = await analyse(MESSAGE, model=llm)

    assert len(llm.calls_for("explainer")) == 1 and result.case.critique.approved


async def test_code_catches_a_contradiction_the_critic_missed():
    llm = fake(critic=[APPROVED, APPROVED], explainer=[SAYS_SAFE, EXPLANATION])
    result = await analyse(MESSAGE, model=llm)

    assert len(llm.calls_for("explainer")) == 2
    assert result.case.explanation.headline == EXPLANATION["headline"]


async def test_critic_loop_is_capped_at_two():
    llm = fake(critic=[REJECTED] * 3, explainer=[SAYS_SAFE] * 3)
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
    assert by_agent["verifier"].model_calls == 1  # tool-call turn; the "done" turn is answered in code
    assert by_agent["parser"].duration_ms > 0


async def test_reasoner_sees_masked_message_and_specialists_already_run():
    llm = fake()
    await analyse(MESSAGE, model=llm)

    prompt = str(llm.calls_for("reasoner")[0].config.system_instruction)
    assert "OTP [OTP] bhejo" in prompt  # the message itself, secret masked
    assert '"specialists_already_run"' in prompt and '"verifier"' in prompt


async def test_useless_loop_back_is_skipped():
    llm = fake(reasoner=[NEEDS_MORE] * 3, explainer=[HEDGED])  # asks for the verifier, whose domains are all checked
    result = await analyse(MESSAGE, model=llm)

    assert len(llm.calls_for("reasoner")) == 1  # no pointless second round
    assert len(llm.calls_for("verifier")) == 1  # first run only; "done" is answered in code
    assert result.case.reasoner_loops == 0  # the cap budget was not used
    assert "reasoner" in result.case.capped_loops
    assert any("no requested specialist" in e.reason for e in result.case.guardrail_events)


async def test_stub_and_pattern_requests_do_not_loop():
    asks_stubs = {**NEEDS_MORE, "requested_specialists": ["pattern", "retrieval", "correlation"]}
    llm = fake(reasoner=[asks_stubs, VERDICT], explainer=[HEDGED])
    await analyse(MESSAGE, model=llm)

    assert len(llm.calls_for("reasoner")) == 1


async def test_loop_back_retries_a_check_the_verifier_skipped():
    only_age = {"__calls__": [TOOL_CALLS["__calls__"][0]]}
    only_reputation = {"__calls__": [TOOL_CALLS["__calls__"][1]]}
    llm = fake(verifier=[only_age, "done", only_reputation, "done"], reasoner=[NEEDS_MORE, VERDICT])
    result = await analyse(MESSAGE, model=llm)

    findings = {f.check: f for f in result.case.verifier_findings}
    assert findings["reputation"].source_tool == "domain_reputation"  # filled on the loop-back
    # run 1: tool turn + "done" turn (a check was still missing); run 2: tool turn only
    assert len(llm.calls_for("verifier")) == 3


async def test_parser_language_is_corrected_by_code():
    english = "Your parcel is on hold. Pay customs fee at http://hdfc-kyc-update.in/verify"
    llm = fake(parser=[{**PARSED, "language": "hi"}])  # LLM wrongly says Hindi
    result = await analyse(english, model=llm)

    assert result.case.parsed.language == "en"
    assert any("language" in e.reason and e.action == "replaced" for e in result.case.guardrail_events)


async def test_english_reply_in_devanagari_is_retried():
    hindi = {**EXPLANATION, "headline": "यह एक स्कैम है"}
    english = "Your parcel is on hold. Pay customs fee at http://hdfc-kyc-update.in/verify"
    llm = fake(parser=[{**PARSED, "language": "en"}], explainer=[hindi, EXPLANATION])
    result = await analyse(english, model=llm)

    assert result.case.explanation.headline == EXPLANATION["headline"]
    retried = [e for e in result.case.guardrail_events if e.action == "retried"]
    assert retried and "explainer" in retried[0].reason
    prompt = str(llm.calls_for("explainer")[0].config.system_instruction)
    assert '"reply_language": "English"' in prompt


async def test_non_domain_text_in_urls_is_not_verified():
    parsed = {**PARSED, "urls": [], "emails": ["Link in email."]}
    llm = fake(parser=[parsed])
    result = await analyse(MESSAGE, model=llm)

    assert llm.calls_for("verifier") == []  # nothing domain-shaped, so no LLM call
    assert result.case.verifier_findings == []


async def test_verifier_tool_loop_is_stopped_in_code():
    # The model never says "done": it keeps calling tools on a stray domain.
    stray = {"__calls__": [{"name": "domain_age", "args": {"indicator": "hdfcbank.com"}}]}
    llm = fake(verifier=[TOOL_CALLS, *[stray] * 20])
    result = await analyse(MESSAGE, model=llm)

    # Turn 1 checks both domains; turn 2 is answered by the guardrail, not the LLM.
    assert len(llm.calls_for("verifier")) == 1
    assert {f.check for f in result.case.verifier_findings} == {"domain_age", "reputation"}


async def test_verifier_turn_budget():
    stray = {"__calls__": [{"name": "domain_age", "args": {"indicator": "hdfcbank.com"}}]}
    llm = fake(verifier=[stray] * 20)  # never checks the real domain
    result = await analyse(MESSAGE, model=llm)

    assert len(llm.calls_for("verifier")) == 4  # budget = 2 x 1 domain + 2
    assert any("turn budget" in e.reason for e in result.case.guardrail_events)
    assert {f.result for f in result.case.verifier_findings} == {CheckResult.UNKNOWN}
