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
import sys
from urllib.parse import urlparse

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from google.genai import types
from mcp import StdioServerParameters

from safespeak.agents.common import case_instruction, llm_callbacks, local_model
from safespeak.blackboard import log_guardrail, post, read_case
from safespeak.schemas import CaseRecord, CheckResult, VerifierFinding, VerifierInput

TOOL_CHECKS = {"domain_age": "domain_age", "domain_reputation": "reputation"}  # tool -> check

PROMPT = """You are the SafeSpeak Verifier.
For EVERY domain in INPUT.domains, call both tools exactly once:
domain_age(indicator=<domain>) and domain_reputation(indicator=<domain>).
Pass the domain exactly as written. When all calls are done, reply "done"."""


def build_input(case: CaseRecord) -> VerifierInput:
    raw = [*case.parsed.urls, *case.parsed.emails]
    hosts = [_host(item) for item in raw]
    return VerifierInput(domains=sorted({h for h in hosts if h}))


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


def skip_if_no_domains(callback_context: CallbackContext) -> types.Content | None:
    """Phone-only messages have nothing for these tools; don't spend an LLM call."""
    if build_input(read_case(callback_context.state)).domains:
        return None
    return types.Content(role="model", parts=[types.Part(text="No domains to verify.")])


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
    done = {(f.indicator, f.check) for f in case.verifier_findings}
    missing = [
        _not_checked(domain, check)
        for domain in build_input(case).domains
        for check in TOOL_CHECKS.values()
        if (domain, check) not in done
    ]
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
        **llm_callbacks(guards=[skip_if_no_domains], after_agent=[fill_unchecked], after_tool=[record_finding]),
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
