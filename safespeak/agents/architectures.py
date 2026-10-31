"""Baseline orchestrations, for comparison with the hierarchical Coordinator.

Same agents, blackboard and guardrails; only the control flow differs:

  sequential: Parser -> all 4 specialists in turn -> Reasoner -> Explainer -> Critic
  parallel:   Parser -> all 4 specialists at once -> Reasoner -> Explainer -> Critic

No runtime routing and no reflection: the Reasoner's request for more evidence
and the Critic's rejection are recorded but not acted on.
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator

from google.adk.agents import BaseAgent, InvocationContext
from google.adk.events import Event

from safespeak.agents.common import state_event
from safespeak.agents.coordinator import Coordinator, _open_case_from_guarded_input
from safespeak.blackboard import post
from safespeak.schemas import CaseStatus, RoutingDecision, Specialist


def _post_fixed_routing(state) -> None:
    decision = RoutingDecision(specialists=list(Specialist), rationale=["Fixed order: no runtime routing."])
    post(state, "routing", decision, CaseStatus.ROUTED)


class SequentialCoordinator(Coordinator):
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        yield state_event(self, ctx, _open_case_from_guarded_input)
        async for event in self._run_validated(ctx, self.parser):
            yield event
        yield state_event(self, ctx, _post_fixed_routing)
        async for event in self._gather_evidence(ctx):
            yield event
        for agent in (self.reasoner, self.explainer, self.critic):
            async for event in self._run_validated(ctx, agent):
                yield event

    async def _gather_evidence(self, ctx) -> AsyncGenerator[Event, None]:
        for agent in self.specialists:
            async for event in agent.run_async(ctx):
                yield event


class ParallelCoordinator(SequentialCoordinator):
    async def _gather_evidence(self, ctx) -> AsyncGenerator[Event, None]:
        async for event in merge_concurrently(self.specialists, ctx):
            yield event


async def merge_concurrently(agents: list[BaseAgent], ctx: InvocationContext) -> AsyncGenerator[Event, None]:
    """Run agents at once, yielding events in the order they happen.

    Each agent waits until its event has been handled before continuing: ADK
    saves events as they are yielded, and an LLM agent's next turn needs its
    own tool results to be saved already. Every write replaces the whole case,
    so saving events in write order also means no agent's section is lost.
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def pump(agent: BaseAgent) -> None:
        try:
            async for event in agent.run_async(ctx):
                handled = asyncio.Event()
                queue.put_nowait((event, handled))
                await handled.wait()
            queue.put_nowait((None, None))
        except Exception as err:
            queue.put_nowait((err, None))

    tasks = [asyncio.create_task(pump(a)) for a in agents]
    running = len(tasks)
    try:
        while running:
            item, handled = await queue.get()
            if isinstance(item, Exception):
                raise item
            if item is None:
                running -= 1
                continue
            yield item
            handled.set()
    finally:
        for task in tasks:
            task.cancel()
