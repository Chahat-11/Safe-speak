"""STUBS for Retrieval and Correlation (real ones: verifier.py, pattern.py).

Each posts an empty-but-valid section so the pipeline runs end to end.
The real versions replace these in a later pass; the Coordinator does not
need to change, because it only knows agent names.
"""

from typing import AsyncGenerator

from google.adk.agents import BaseAgent, InvocationContext
from google.adk.events import Event

from safespeak.agents.common import state_event, trace_callbacks
from safespeak.blackboard import post
from safespeak.schemas import CorrelationResult, Specialist

# specialist -> (case section it owns, empty value to post)
_STUB_OUTPUT = {
    Specialist.RETRIEVAL: ("retrieved_evidence", []),
    Specialist.CORRELATION: ("correlation", CorrelationResult(summary="Stub: correlation not implemented yet.")),
}


class StubSpecialist(BaseAgent):
    """Placeholder agent: writes an empty result to its own case section."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        section, value = _STUB_OUTPUT[Specialist(self.name)]
        yield state_event(self, ctx, lambda state: post(state, section, value))


def create_stub_specialists() -> list[BaseAgent]:
    return [StubSpecialist(name=s.value, **trace_callbacks()) for s in _STUB_OUTPUT]
