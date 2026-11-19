"""A2A round trip: an ADK RemoteA2aAgent asks the SafeSpeak A2A server, in-process."""

import httpx

from safespeak.a2a.client import ask
from safespeak.a2a.server import build_app
from tests.fake_llm import DOMAIN
from tests.test_pipeline import MESSAGE, fake

BASE = "http://127.0.0.1:8010"


async def test_agent_card_describes_safespeak():
    app = build_app(model=fake())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as http:
            card = (await http.get("/.well-known/agent-card.json")).json()
    assert card["name"] == "safespeak"
    assert "scam" in card["description"]


async def test_remote_agent_gets_a_verdict_over_a2a():
    app = build_app(model=fake())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE, timeout=60) as http:
            reply = await ask(MESSAGE, card_url=f"{BASE}/.well-known/agent-card.json", http=http)
    assert "Scam" in reply or "scam" in reply
    assert "482913" not in reply  # the OTP stays masked across the protocol too
    assert DOMAIN in reply or "link" in reply.lower()
