"""A CrewAI agent that consults SafeSpeak (an ADK agent) over A2A.

  terminal 1: .venv/bin/python -m safespeak.a2a serve                   (ADK side)
  terminal 2: .venv-crews/bin/python -m safespeak.crews ask "message"   (CrewAI side)

This is the cross-framework hop: the caller is defined in CrewAI, the callee
in ADK, and they share nothing but the A2A protocol. CrewAI 1.15's A2A client
speaks protocol 0.3 and ADK's server 1.0; SafeSpeak serves a 0.3 copy of its
agent card and ADK's endpoint accepts both, so the two interoperate.

Why a tool and not CrewAI's `a2a=` setting: with `a2a=`, the CrewAI agent's
LLM decides whether to delegate, and qwen2.5:3b answered by itself instead.
The tool makes the A2A call with CrewAI's own delegation client
(execute_a2a_delegation), and result_as_answer=True returns SafeSpeak's
verdict unchanged, so the small model cannot rewrite it.
"""

from __future__ import annotations

from safespeak.crews.runtime import local_llm

from crewai import Agent, Crew, Process, Task  # noqa: E402
from crewai.a2a.utils.delegation import execute_a2a_delegation  # noqa: E402
from crewai.tools import BaseTool  # noqa: E402

from safespeak import config  # noqa: E402

# CrewAI's A2A client speaks protocol 0.3, so it reads the 0.3 copy of the card.
CARD_URL = f"{config.A2A_PUBLIC_URL}/.well-known/agent-card-v0.3.json"


class AskSafeSpeak(BaseTool):
    name: str = "ask_safespeak"
    description: str = "Send a suspicious message to the remote SafeSpeak agent over A2A and get its scam verdict."

    def _run(self, message: str) -> str:
        reply = execute_a2a_delegation(endpoint=CARD_URL, auth=None, timeout=600, task_description=message)
        if reply.get("status") != "completed":
            return f"SafeSpeak could not be reached over A2A: {reply.get('error') or reply.get('status')}"
        return _once(reply.get("result") or "")


def build_crew(text: str) -> Crew:
    desk = Agent(
        role="Fraud Help Desk Assistant",
        goal="Get an expert scam verdict for the customer's message",
        backstory="You never judge messages yourself. You always use the ask_safespeak tool.",
        llm=local_llm(), tools=[AskSafeSpeak(result_as_answer=True)],
        allow_delegation=False, verbose=False,
    )
    check = Task(
        description=f"Use the ask_safespeak tool on this exact message:\n\n{text}",
        expected_output="SafeSpeak's verdict, reasons and advice, unchanged.",
        agent=desk,
    )
    return Crew(agents=[desk], tasks=[check], process=Process.sequential, verbose=False, tracing=False)


def run(text: str) -> str:
    return str(build_crew(text).kickoff())


def _once(text: str) -> str:
    """The streamed reply can arrive twice (artifact + final status); keep one copy."""
    text = text.strip()
    second = text.find(text[:40], 1) if len(text) > 80 else -1
    if second > 0 and text[second:].strip() == text[:second].strip():
        return text[:second].strip()
    return text
