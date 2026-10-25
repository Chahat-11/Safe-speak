"""Builds the live ADK service.

  SafeSpeakService: one runner (and one MCP server subprocess) reused for
                    many messages; each message gets its own fresh session.
  analyse(text):    convenience wrapper for a single message.
"""

from __future__ import annotations

import logging
import uuid

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel

from safespeak.agents.coordinator import Coordinator, create_coordinator
from safespeak.agents.critic import create_critic
from safespeak.agents.explainer import create_explainer
from safespeak.agents.parser import create_parser
from safespeak.agents.pattern import create_pattern_specialist
from safespeak.agents.reasoner import create_reasoner
from safespeak.agents.router import create_router
from safespeak.agents.specialists import create_stub_specialists
from safespeak.agents.verifier import create_verifier
from safespeak.blackboard import CASE_KEY
from safespeak.observability.tracer import tracer
from safespeak.schemas import CaseRecord, RunMetrics

APP_NAME = "safespeak"
USER_ID = "local-user"

# ADK guesses an app name from any folder called "agents/" (an `adk web`
# convention) and warns when it differs. That guess is wrong for our layout.
logging.getLogger("google_adk.google.adk.runners").setLevel(logging.ERROR)


class AnalysisResult(BaseModel):
    markdown: str
    case: CaseRecord | None  # None when the input guardrail blocked the message
    metrics: RunMetrics


def build_root_agent(model=None) -> Coordinator:
    """Wire the agent tree. `model` lets tests swap in a fake LLM."""
    return create_coordinator(
        parser=create_parser(model),
        router=create_router(),
        specialists=[create_verifier(model), create_pattern_specialist(), *create_stub_specialists()],
        reasoner=create_reasoner(model),
        explainer=create_explainer(model),
        critic=create_critic(model),
    )


class SafeSpeakService:
    """Use as `async with SafeSpeakService() as svc: await svc.analyse(text)`."""

    def __init__(self, model=None):
        self.sessions = InMemorySessionService()
        self.runner = Runner(agent=build_root_agent(model), app_name=APP_NAME, session_service=self.sessions)

    async def __aenter__(self) -> "SafeSpeakService":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.runner.close()  # also stops the MCP server subprocess

    async def analyse(self, text: str) -> AnalysisResult:
        """Run one message through the pipeline in a fresh session."""
        session = await self.sessions.create_session(app_name=APP_NAME, user_id=USER_ID, session_id=uuid.uuid4().hex)
        message = types.Content(role="user", parts=[types.Part(text=text)])
        markdown, invocation_id = "", ""
        async for event in self.runner.run_async(user_id=USER_ID, session_id=session.id, new_message=message):
            invocation_id = event.invocation_id
            if event.author == "coordinator" and event.content and event.content.parts:
                markdown = "".join(p.text or "" for p in event.content.parts)

        final = await self.sessions.get_session(app_name=APP_NAME, user_id=USER_ID, session_id=session.id)
        raw_case = final.state.get(CASE_KEY)
        case = CaseRecord.model_validate(raw_case) if raw_case else None
        metrics = tracer.finish_run(invocation_id, case.case_id if case else None)
        return AnalysisResult(markdown=markdown, case=case, metrics=metrics)


async def analyse(text: str, model=None) -> AnalysisResult:
    async with SafeSpeakService(model) as service:
        return await service.analyse(text)
