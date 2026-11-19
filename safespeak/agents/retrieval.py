"""Retrieval specialist: finds known past cases similar to this message.

Reads:  case.message_text (already redacted)
Writes: case.retrieved_evidence  (list of RetrievedEvidence)

Rule-based like the Pattern specialist: no LLM, no network, deterministic.
The search itself lives in retrieval_index.py (no ADK there, easy to test).
"""

from typing import AsyncGenerator

from google.adk.agents import BaseAgent, InvocationContext
from google.adk.events import Event

from safespeak.agents.common import state_event, trace_callbacks
from safespeak.agents.retrieval_index import search
from safespeak.blackboard import post, read_case


class RetrievalSpecialist(BaseAgent):
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        yield state_event(self, ctx, _post_evidence)


def _post_evidence(state) -> None:
    post(state, "retrieved_evidence", search(read_case(state).message_text))


def create_retrieval_specialist() -> RetrievalSpecialist:
    return RetrievalSpecialist(name="retrieval", **trace_callbacks())
