"""Shared building blocks for every agent.

make_llm_agent() is the one place an LLM agent is wired up, so all of them
get the same rules:
  - input:  a typed model built from the CaseRecord, shown as JSON
  - output: a Pydantic output_schema; the raw reply goes to a temp: key
  - after the run, post_output() validates it and posts it to the blackboard
  - guardrail + tracing callbacks attached in a fixed order
"""

from __future__ import annotations

import json
from typing import Callable

from google.adk.agents import BaseAgent, InvocationContext, LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.events import Event, EventActions
from google.adk.models.lite_llm import LiteLlm
from google.adk.sessions.state import State
from pydantic import BaseModel

from safespeak import config
from safespeak.blackboard import post, read_case
from safespeak.guardrails.model_guard import isolate_llm_request
from safespeak.observability.tracer import tracer
from safespeak.schemas import CaseRecord, CaseStatus


def local_model() -> LiteLlm:
    """The Ollama model every LLM agent uses (nothing leaves this machine)."""
    return LiteLlm(model=config.MODEL, api_base=config.OLLAMA_API_BASE)


def trace_callbacks() -> dict:
    """Agent-level tracing callbacks, for agents that are not LLM agents."""
    return {"before_agent_callback": [tracer.before_agent], "after_agent_callback": [tracer.after_agent]}


def state_event(agent: BaseAgent, ctx: InvocationContext, change: Callable[[State], None]) -> Event:
    """Apply `change` to session state and wrap the delta in an Event.

    Custom (non-LLM) agents must yield their state changes as events,
    otherwise the session service never persists them.
    """
    delta: dict = {}
    change(State(value=ctx.session.state, delta=delta))
    return Event(
        invocation_id=ctx.invocation_id,
        author=agent.name,
        branch=ctx.branch,
        actions=EventActions(state_delta=delta),
    )


def make_llm_agent(
    *,
    name: str,
    prompt: str,
    build_input: Callable[[CaseRecord], BaseModel],
    output_schema: type[BaseModel],
    section: str,
    status: CaseStatus,
    model=None,
    guards: list[Callable] | None = None,
) -> LlmAgent:
    """Create an LLM agent that reads the case and writes one case section.

    `guards`: extra before_agent callbacks (e.g. a loop cap) run after tracing.
    """
    output_key = f"temp:{name}_output"
    schema = json.dumps(output_schema.model_json_schema())
    suffix = f"\n\nReply with one JSON object matching this schema:\n{schema}"

    def post_output(callback_context: CallbackContext) -> None:
        # Raises pydantic.ValidationError on bad output -> Coordinator retries.
        value = output_schema.model_validate(callback_context.state[output_key])
        post(callback_context.state, section, value, status)

    return LlmAgent(
        name=name,
        model=model or local_model(),
        instruction=case_instruction(prompt, build_input, suffix),
        include_contents="none",
        output_schema=output_schema,
        output_key=output_key,
        **llm_callbacks(guards=guards, after_agent=[post_output]),
    )


def case_instruction(prompt: str, build_input: Callable[[CaseRecord], BaseModel], suffix: str = ""):
    """Instruction provider: role prompt + the agent's typed input as JSON."""

    def instruction(ctx: ReadonlyContext) -> str:
        payload = build_input(read_case(ctx.state))
        return f"{prompt}\n\nINPUT (JSON):\n{payload.model_dump_json(indent=2)}{suffix}"

    return instruction


def llm_callbacks(*, guards=None, after_agent=None, after_tool=None) -> dict:
    """The fixed callback order for every LLM agent: tracing wraps everything.

    guards      -> before_agent, after tracing starts (may skip the agent)
    after_agent -> before tracing ends (so the trace sees what they posted)
    after_tool  -> before tool tracing
    """
    return {
        "before_agent_callback": [tracer.before_agent, *(guards or [])],
        "after_agent_callback": [*(after_agent or []), tracer.after_agent],
        "before_model_callback": [isolate_llm_request, tracer.before_model],
        "after_model_callback": [tracer.after_model],
        "before_tool_callback": [tracer.before_tool],
        "after_tool_callback": [*(after_tool or []), tracer.after_tool],
    }
