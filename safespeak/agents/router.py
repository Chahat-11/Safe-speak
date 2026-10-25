"""The Coordinator's routing step, as its own small agent.

Why a separate agent: the Reasoner -> Coordinator loop must be capped by a
before_agent callback. Making routing an agent gives that callback a place
to run on every (re-)entry. See guardrails/loop_caps.py.

Routing is plain Python rules, not an LLM: cheap, deterministic, auditable.
"""

from typing import AsyncGenerator

from google.adk.agents import BaseAgent, InvocationContext
from google.adk.events import Event

from safespeak.agents.common import state_event
from safespeak.blackboard import post, read_case
from safespeak.guardrails.loop_caps import cap_reasoner_loops
from safespeak.observability.tracer import tracer
from safespeak.schemas import CaseRecord, CaseStatus, RoutingDecision, Specialist


def route(case: CaseRecord) -> RoutingDecision:
    """Pick specialists. On a loop-back, run only what the Reasoner asked for."""
    if case.verdict and case.verdict.requested_specialists:
        return RoutingDecision(
            specialists=case.verdict.requested_specialists,
            rationale=["Reasoner requested more evidence."],
        )

    parsed = case.parsed
    has_indicators = bool(parsed.urls or parsed.phone_numbers or parsed.emails)
    chosen = [Specialist.PATTERN, Specialist.RETRIEVAL]
    why = ["Pattern and Retrieval always run."]
    if has_indicators:
        chosen += [Specialist.VERIFIER, Specialist.CORRELATION]
        why.append("Message has URLs/phones/emails to verify and correlate.")
    return RoutingDecision(specialists=chosen, rationale=why)


class Router(BaseAgent):
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        yield state_event(self, ctx, _post_routing)


def _post_routing(state) -> None:
    post(state, "routing", route(read_case(state)), CaseStatus.ROUTED)


def create_router() -> Router:
    return Router(
        name="router",
        before_agent_callback=[tracer.before_agent, cap_reasoner_loops],
        after_agent_callback=[tracer.after_agent],
    )
