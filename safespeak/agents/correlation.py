"""Correlation specialist: links this case to earlier cases (scam waves).

Reads:  case.parsed (its links, emails and phone numbers)
Writes: case.correlation  (CorrelationResult)

Rule-based: no LLM, no network. The memory of earlier cases is
safespeak/case_history.py; app.py adds each finished case to it.
"""

from typing import AsyncGenerator

from google.adk.agents import BaseAgent, InvocationContext
from google.adk.events import Event

from safespeak.agents.common import state_event, trace_callbacks
from safespeak.blackboard import post, read_case
from safespeak.case_history import correlate


class CorrelationSpecialist(BaseAgent):
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        yield state_event(self, ctx, _post_correlation)


def _post_correlation(state) -> None:
    post(state, "correlation", correlate(read_case(state)))


def create_correlation_specialist() -> CorrelationSpecialist:
    return CorrelationSpecialist(name="correlation", **trace_callbacks())
