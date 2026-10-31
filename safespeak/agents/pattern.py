"""Pattern specialist: matches the message against the scam-pattern catalogue.

Reads:  case.message_text (already redacted)
Writes: case.pattern_matches  (list of PatternMatch)

Rule-based on purpose, no LLM call: deterministic, fast (milliseconds), and
every match names the exact cues that fired, so the Reasoner (and a viva
examiner) can see why. No tools are used, so it needs no MCP server.
"""

from typing import AsyncGenerator

from google.adk.agents import BaseAgent, InvocationContext
from google.adk.events import Event

from safespeak.agents.common import state_event, trace_callbacks
from safespeak.agents.pattern_matcher import match_patterns
from safespeak.blackboard import post, read_case

class PatternSpecialist(BaseAgent):
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        yield state_event(self, ctx, _post_matches)


def _post_matches(state) -> None:
    post(state, "pattern_matches", match_patterns(read_case(state).message_text))


def create_pattern_specialist() -> PatternSpecialist:
    return PatternSpecialist(name="pattern", **trace_callbacks())
