"""Coordinator: the root agent that drives the live pipeline.

  input guardrail (before_agent callback)
  -> open case -> Parser -> Router -> specialists -> Reasoner
     (loop back to Router while the Reasoner wants more evidence; capped)
  -> Explainer -> Critic
     (loop back to Explainer while the Critic rejects; capped)
  -> output guardrail (after_agent callback, renders Markdown)

Caps are enforced by before_agent callbacks (guardrails/loop_caps.py). The
Coordinator only reads case.capped_loops to know a loop was closed.

The Coordinator never passes data to agents directly. It only decides WHICH
agent runs next by reading the blackboard; agents read/write the case.
"""

from __future__ import annotations

from typing import AsyncGenerator

from google.adk.agents import BaseAgent, InvocationContext
from google.adk.events import Event

from safespeak.agents.common import state_event
from safespeak.blackboard import log_guardrail, loop_is_closed, open_case, post, read_case
from safespeak.guardrails.input_guard import GUARDED_INPUT_KEY, input_guardrail
from safespeak.guardrails.output_guard import output_guardrail
from safespeak.observability.tracer import tracer
from safespeak.schemas import MAX_VALIDATION_RETRIES, GuardedInput


class SchemaViolation(RuntimeError):
    """An LLM agent produced invalid output even after the retry."""


class Coordinator(BaseAgent):
    parser: BaseAgent
    router: BaseAgent
    specialists: list[BaseAgent]
    reasoner: BaseAgent
    explainer: BaseAgent
    critic: BaseAgent

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        yield state_event(self, ctx, _open_case_from_guarded_input)
        async for event in self._run_validated(ctx, self.parser):
            yield event
        async for event in self.router.run_async(ctx):
            yield event

        while True:
            async for event in self._run_specialists(ctx):
                yield event
            async for event in self._run_validated(ctx, self.reasoner):
                yield event
            if not _wants_more_evidence(ctx):
                break
            async for event in self.router.run_async(ctx):  # cap may veto
                yield event
            if loop_is_closed(ctx.session.state, "reasoner"):
                break

        async for event in self._run_validated(ctx, self.explainer):
            yield event
        while True:
            async for event in self._run_validated(ctx, self.critic):
                yield event
            if _critic_approved(ctx):
                break
            async for event in self._run_validated(ctx, self.explainer):  # cap may veto
                yield event
            if loop_is_closed(ctx.session.state, "critic"):
                break

    async def _run_specialists(self, ctx) -> AsyncGenerator[Event, None]:
        """Run only the specialists named in the current RoutingDecision."""
        chosen = {s.value for s in read_case(ctx.session.state).routing.specialists}
        for agent in self.specialists:
            if agent.name in chosen:
                async for event in agent.run_async(ctx):
                    yield event

    async def _run_validated(self, ctx, agent: BaseAgent) -> AsyncGenerator[Event, None]:
        """Run an LLM agent; on invalid output retry once, then raise."""
        for attempt in range(MAX_VALIDATION_RETRIES + 1):
            try:
                async for event in agent.run_async(ctx):
                    yield event
                return
            except ValueError as err:  # pydantic.ValidationError is a ValueError
                gave_up = attempt == MAX_VALIDATION_RETRIES
                yield state_event(self, ctx, _log_invalid_output(agent.name, err, gave_up))
                if gave_up:
                    raise SchemaViolation(f"{agent.name} output failed validation twice") from err


def _open_case_from_guarded_input(state) -> None:
    guarded = GuardedInput.model_validate(state[GUARDED_INPUT_KEY])
    open_case(state, guarded.text)
    post(state, "guardrail_events", guarded.events)


def _wants_more_evidence(ctx: InvocationContext) -> bool:
    verdict = read_case(ctx.session.state).verdict
    return bool(verdict and verdict.needs_more_evidence)


def _critic_approved(ctx: InvocationContext) -> bool:
    critique = read_case(ctx.session.state).critique
    return bool(critique and critique.approved)


def _log_invalid_output(agent_name: str, err: Exception, gave_up: bool):
    action = "failed" if gave_up else "retried"
    reason = f"{agent_name} output invalid: {str(err).splitlines()[0][:200]}"
    return lambda state: log_guardrail(state, "agent", action, reason)


def create_coordinator(*, parser, router, specialists, reasoner, explainer, critic) -> Coordinator:
    return Coordinator(
        name="coordinator",
        parser=parser,
        router=router,
        specialists=specialists,
        reasoner=reasoner,
        explainer=explainer,
        critic=critic,
        sub_agents=[parser, router, *specialists, reasoner, explainer, critic],
        # Order matters: tracing first, then guardrails (a guardrail that
        # returns content stops the callbacks after it).
        before_agent_callback=[tracer.before_agent, input_guardrail],
        after_agent_callback=[tracer.after_agent, output_guardrail],
    )
