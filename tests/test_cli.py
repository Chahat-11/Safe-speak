"""CLI output modes: Markdown by default, CaseRecord JSON with --json."""

import json

import pytest

from safespeak import __main__ as cli
from safespeak.app import analyse
from safespeak.schemas import CaseRecord
from tests.fake_llm import APPROVED, EXPLANATION, PARSED, TOOL_CALLS, VERDICT, FakeLlm

MESSAGE = "HDFC: KYC pending. OTP 482913 bhejo http://hdfc-kyc-update.in/verify"


def _fake() -> FakeLlm:
    script = {"parser": [PARSED], "verifier": [TOOL_CALLS, "done"], "reasoner": [VERDICT],
              "explainer": [EXPLANATION], "critic": [APPROVED]}
    return FakeLlm(script=script, requests=[])


@pytest.fixture
def run_cli(monkeypatch, capsys):
    """Run main() with the fake LLM swapped in; return stdout."""
    async def fake_analyse(text):
        return await analyse(text, model=_fake())

    def run(*argv):
        monkeypatch.setattr(cli, "analyse", fake_analyse)
        cli.main(list(argv))
        return capsys.readouterr().out

    return run


def test_default_output_is_markdown(run_cli):
    out = run_cli(MESSAGE)
    assert out.startswith("## ⚠️ This is a scam")


def test_json_flag_prints_case_record(run_cli):
    out = run_cli("--json", MESSAGE)
    case = CaseRecord.model_validate_json(out)  # stdout is exactly one CaseRecord
    assert case.verdict.label == "scam"
    assert case.explanation.headline == EXPLANATION["headline"]
    assert "482913" not in out


def test_json_flag_on_blocked_input(run_cli):
    out = run_cli("--json", "   ")
    data = json.loads(out)
    assert data["case"] is None and data["blocked"] is True
