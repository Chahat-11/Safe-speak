"""SafeSpeak as an A2A agent: other agents can send it a message to check.

  python -m safespeak.a2a serve      -> http://127.0.0.1:8010
  agent card: http://127.0.0.1:8010/.well-known/agent-card.json

A2A is the open protocol for agents in different programs (or companies) to
call each other: the server publishes an "agent card" saying what it can do,
and clients send it tasks as JSON-RPC over HTTP. ADK turns any ADK agent into
an A2A server with `to_a2a`.

What we expose is one thin ADK agent, SafeSpeakA2aAgent. It hands the text to
the same SafeSpeakService the CLI and the run monitor use, so guardrails,
tracing, RunMetrics and the case history all behave exactly the same. Inside,
the nine agents still coordinate only through the blackboard; A2A is the
system's front door, not a way for our own agents to talk to each other.

Local only by default: binds to 127.0.0.1, because messages may hold OTPs and
account numbers. SAFESPEAK_A2A_HOST / _PORT change where it listens, and
SAFESPEAK_A2A_PUBLIC_URL the address written into the agent card (config.py).
One message at a time, because the local model runs one request.

Two agent cards, one endpoint. ADK speaks A2A protocol 1.0 and publishes its
card at /.well-known/agent-card.json. CrewAI 1.15 ships the older 0.3 client,
which cannot read a 1.0 card, so the same card is also served in 0.3 format at
LEGACY_CARD_PATH. The JSON-RPC endpoint accepts both protocol versions (ADK
enables a2a-sdk's v0.3 compatibility), so a CrewAI agent and an ADK agent can
both call SafeSpeak: interoperability across the two frameworks.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from urllib.parse import urlparse

from a2a.compat.v0_3.conversions import to_compat_agent_card
from google.adk.a2a.utils.agent_card_builder import AgentCardBuilder
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.adk.agents import BaseAgent, InvocationContext
from google.adk.events import Event
from google.genai import types
from pydantic import PrivateAttr
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from safespeak import config
from safespeak.app import SafeSpeakService

LEGACY_CARD_PATH = "/.well-known/agent-card-v0.3.json"

DESCRIPTION = (
    "SafeSpeak checks a suspicious SMS, email or WhatsApp message (English, Hindi or Hinglish) "
    "for scams and phishing. Send the message text; it replies with a verdict (scam, suspicious, "
    "likely safe or uncertain), the reasons, and what to do next. Runs on a local model; secrets "
    "such as OTPs are masked before any agent reads them."
)


class SafeSpeakA2aAgent(BaseAgent):
    """Bridges one A2A task to one SafeSpeak analysis."""

    _service: SafeSpeakService | None = PrivateAttr(default=None)
    _lock: asyncio.Lock = PrivateAttr(default_factory=asyncio.Lock)

    def use(self, service: SafeSpeakService) -> None:
        self._service = service

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        text = _text_of(ctx.user_content)
        async with self._lock:
            result = await self._service.analyse(text)
        reply = types.Content(role="model", parts=[types.Part(text=result.markdown)])
        yield Event(author=self.name, invocation_id=ctx.invocation_id, content=reply)


def build_app(model=None, public_url: str | None = None) -> Starlette:
    """The A2A web app. `model` lets tests swap in a fake LLM.

    `public_url` is where other agents reach us; it goes into the agent card.
    """
    agent = SafeSpeakA2aAgent(name="safespeak", description=DESCRIPTION)
    protocol, host, port = card_address(public_url or config.A2A_PUBLIC_URL)

    @asynccontextmanager
    async def lifespan(_app: Starlette):
        async with SafeSpeakService(model) as service:  # one MCP server for the whole session
            agent.use(service)
            yield

    app = to_a2a(agent, protocol=protocol, host=host, port=port, lifespan=lifespan)
    rpc_url = f"{protocol}://{host}:{port}/"
    app.router.routes.append(Route(LEGACY_CARD_PATH, legacy_card_endpoint(agent, rpc_url)))
    return app


def legacy_card_endpoint(agent: BaseAgent, rpc_url: str):
    """Serve our agent card in A2A 0.3 format, for CrewAI's A2A client."""
    cached: dict = {}

    async def endpoint(_request: Request) -> JSONResponse:
        if not cached:
            card = await AgentCardBuilder(agent=agent, rpc_url=rpc_url).build()
            card.supported_interfaces.add(url=rpc_url, protocol_binding="JSONRPC", protocol_version="0.3")
            cached.update(to_compat_agent_card(card).model_dump(mode="json", by_alias=True, exclude_none=True))
        return JSONResponse(cached)

    return endpoint


def card_address(url: str) -> tuple[str, str, int]:
    """'https://safespeak.example.com' -> ('https', 'safespeak.example.com', 443)."""
    parts = urlparse(url)
    default_port = 443 if parts.scheme == "https" else 80
    return parts.scheme or "http", parts.hostname or "127.0.0.1", parts.port or default_port


def _text_of(content: types.Content | None) -> str:
    if content is None or not content.parts:
        return ""
    return "".join(part.text or "" for part in content.parts)
