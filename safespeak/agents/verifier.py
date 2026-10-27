"""Verifier specialist: checks every domain in the message via our MCP server.

Reads:  parsed.urls + parsed.emails  (as VerifierInput.domains)
Writes: case.verifier_findings

How a finding gets onto the blackboard:
  1. The LLM decides to call domain_age / domain_reputation (MCP tools).
  2. Our MCP server returns a VerifierFinding as structured content.
  3. record_finding (after_tool callback) validates it and posts it.
So findings come from tool results in code; the LLM cannot invent one.
fill_unchecked (after_agent) then marks any check the LLM skipped as
"unknown" and logs it, so gaps are visible instead of silent.
"""

import os
import re
import sys
from urllib.parse import urlparse

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from google.genai import types
from mcp import StdioServerParameters

from safespeak.agents.common import case_instruction, llm_callbacks, local_model
from safespeak.blackboard import log_guardrail, post, read_case
from safespeak.schemas import CaseRecord, CheckResult, VerifierFinding, VerifierInput

TOOL_CHECKS = {"domain_age": "domain_age", "domain_reputation": "reputation"}  # tool -> check
TURNS_KEY = "temp:verifier_turns"
# A host: dot-separated labels of letters/digits/hyphens, ending in a 2+ letter TLD.
_HOST = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}$")

PROMPT = """You are the SafeSpeak Verifier.
For EVERY domain in INPUT.domains, call both tools exactly once:
domain_age(indicator=<domain>) and domain_reputation(indicator=<domain>).
Pass the domain exactly as written. When all calls are done, reply "done"."""


def build_input(case: CaseRecord) -> VerifierInput:
    raw = [*case.parsed.urls, *case.parsed.emails]
    hosts = [_host(item) for item in raw]
    # The Parser sometimes puts plain words in urls/emails ("Link in email.").
    return VerifierInput(domains=sorted({h for h in hosts if _HOST.match(h)}))


def mcp_tools() -> McpToolset:
    """Start our MCP server as a subprocess and expose only its two tools."""
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "safespeak.mcp_server"],
        env=dict(os.environ),  # pass through config such as SAFESPEAK_CACHE_DIR
    )
    return McpToolset(
        connection_params=StdioConnectionParams(server_params=server, timeout=30),
        tool_filter=list(TOOL_CHECKS),
    )


def skip_if_nothing_to_check(callback_context: CallbackContext) -> types.Content | None:
    """Don't spend an LLM call when every domain already has real tool results.

    Covers phone-only messages (no domains) and Reasoner loop-backs that
    re-route to the Verifier for domains it has already checked.
    """
    case = read_case(callback_context.state)
    if _unchecked(case):
        callback_context.state[TURNS_KEY] = 0  # fresh turn budget for this run
        return None
    return types.Content(role="model", parts=[types.Part(text="Nothing new to verify.")])


def stop_when_done(callback_context: CallbackContext, llm_request: LlmRequest) -> LlmResponse | None:
    """before_model guardrail: end the tool loop in code, not by trusting the LLM.

    ADK lets an agent call tools forever. Once every domain x check has a real
    result, or the turn budget (2 per domain + 2) is spent, answer "done"
    instead of calling the model again.
    """
    state = callback_context.state
    case = read_case(state)
    turns = state.get(TURNS_KEY, 0) + 1
    state[TURNS_KEY] = turns
    budget = 2 * len(build_input(case).domains) + 2
    if not _unchecked(case) or turns > budget:
        if turns > budget:
            log_guardrail(state, "tool", "blocked", f"Verifier turn budget ({budget}) reached.")
        return LlmResponse(content=types.Content(role="model", parts=[types.Part(text="done")]))
    return None


def _unchecked(case: CaseRecord) -> list[tuple[str, str]]:
    """(domain, check) pairs without a real tool result. Gap-fillers don't count."""
    done = {(f.indicator, f.check) for f in case.verifier_findings if f.source_tool != "none"}
    return [
        (domain, check)
        for domain in build_input(case).domains
        for check in TOOL_CHECKS.values()
        if (domain, check) not in done
    ]


def record_finding(tool, args: dict, tool_context, tool_response) -> None:
    """after_tool callback: MCP structured result -> VerifierFinding -> case."""
    if not isinstance(tool_response, dict) or tool_response.get("isError"):
        return None
    content = tool_response.get("structuredContent")
    if not content:
        return None
    finding = VerifierFinding.model_validate(content)
    host = _host(finding.indicator)
    state = tool_context.state
    if host not in build_input(read_case(state)).domains:
        log_guardrail(state, "tool", "flagged", f"Ignored {tool.name} result for {host!r}: not in the message.")
        return None
    _merge_findings(state, [finding.model_copy(update={"indicator": host})])
    return None


def fill_unchecked(callback_context: CallbackContext) -> None:
    """after_agent callback: every domain x check gets a finding, even if skipped."""
    state = callback_context.state
    case = read_case(state)
    have = {(f.indicator, f.check) for f in case.verifier_findings}
    missing = [_not_checked(d, c) for d, c in _unchecked(case) if (d, c) not in have]
    if missing:
        _merge_findings(state, missing)
        log_guardrail(state, "tool", "flagged", f"Verifier skipped {len(missing)} check(s); marked unknown.")


def create_verifier(model=None) -> LlmAgent:
    return LlmAgent(
        name="verifier",
        model=model or local_model(),
        instruction=case_instruction(PROMPT, build_input),
        include_contents="none",
        tools=[mcp_tools()],
        **llm_callbacks(
            guards=[skip_if_nothing_to_check],
            model_guards=[stop_when_done],
            after_agent=[fill_unchecked],
            after_tool=[record_finding],
        ),
    )


def _merge_findings(state, new: list[VerifierFinding]) -> None:
    """Replace any earlier finding for the same (indicator, check); keep the rest."""
    keys = {(f.indicator, f.check) for f in new}
    kept = [f for f in read_case(state).verifier_findings if (f.indicator, f.check) not in keys]
    post(state, "verifier_findings", [*kept, *new])


def _not_checked(domain: str, check: str) -> VerifierFinding:
    return VerifierFinding(
        indicator=domain, indicator_type="domain", check=check,
        result=CheckResult.UNKNOWN, detail="Check was not run.", source_tool="none",
    )


def _host(item: str) -> str:
    item = item.strip().lower()
    if "@" in item and "/" not in item:
        return item.rsplit("@", 1)[1]
    if "://" not in item:
        item = "http://" + item
    return (urlparse(item).hostname or "").removeprefix("www.")
