"""A second ADK agent that consults SafeSpeak over A2A.

  python -m safespeak.a2a ask "Your KYC expires today, click http://..."

RemoteA2aAgent is ADK's A2A client: it reads SafeSpeak's agent card, sends the
message as an A2A task over HTTP, and turns the reply back into ADK events.
This is the agent-to-agent hop: the caller knows nothing about SafeSpeak's
insides, only its published card.
"""

from __future__ import annotations

import uuid

import httpx
from google.adk.a2a.agent import RemoteA2aAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from safespeak import config

CARD_URL = f"{config.A2A_PUBLIC_URL}/.well-known/agent-card.json"


async def ask(text: str, card_url: str = CARD_URL, http: httpx.AsyncClient | None = None) -> str:
    """Send one message to the SafeSpeak A2A agent and return its reply.

    `http` lets tests talk to the server in-process instead of over a socket.
    """
    http = http or httpx.AsyncClient(timeout=600)  # a local 3B model can take a minute
    remote = RemoteA2aAgent(name="safespeak_remote", agent_card=card_url, httpx_client=http,
                            description="Remote SafeSpeak scam checker, reached over A2A.")
    sessions = InMemorySessionService()
    runner = Runner(agent=remote, app_name="safespeak_client", session_service=sessions)
    session = await sessions.create_session(app_name="safespeak_client", user_id="client", session_id=uuid.uuid4().hex)
    message = types.Content(role="user", parts=[types.Part(text=text)])
    reply = ""
    try:
        async for event in runner.run_async(user_id="client", session_id=session.id, new_message=message):
            if event.content and event.content.parts:
                reply = "".join(part.text or "" for part in event.content.parts) or reply
    finally:
        await runner.close()
    return reply
