"""A scripted stand-in for Ollama so the pipeline can be tested offline.

Each agent's prompt starts with "You are the SafeSpeak <Role>"; the fake
looks that up and pops the next scripted reply for that role.
A reply of {"__calls__": [...]} becomes tool (function) calls.
Every request it receives is kept in .requests for assertions.
"""

import json
from typing import AsyncGenerator

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

ROLES = ("Parser", "Verifier", "Reasoner", "Explainer", "Critic")


class FakeLlm(BaseLlm):
    model: str = "fake"
    script: dict[str, list] = {}
    requests: list[LlmRequest] = []

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        self.requests.append(llm_request)
        reply = self.script[role_of(llm_request)].pop(0)
        yield LlmResponse(
            content=types.Content(role="model", parts=_parts(reply)),
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=100, candidates_token_count=20
            ),
        )

    def calls_for(self, role: str) -> list[LlmRequest]:
        return [r for r in self.requests if role_of(r) == role]


def role_of(request: LlmRequest) -> str:
    instruction = str(request.config.system_instruction)
    for role in ROLES:
        if f"You are the SafeSpeak {role}" in instruction:
            return role.lower()
    raise AssertionError("Unknown agent prompt")


def _parts(reply) -> list[types.Part]:
    if isinstance(reply, dict) and "__calls__" in reply:
        return [types.Part(function_call=types.FunctionCall(name=c["name"], args=c["args"])) for c in reply["__calls__"]]
    text = reply if isinstance(reply, str) else json.dumps(reply)
    return [types.Part(text=text)]


DOMAIN = "hdfc-kyc-update.in"
PARSED = {
    "channel": "sms", "language": "hinglish", "sender": "VM-HDFCBK",
    "claimed_organisation": "HDFC Bank", "urls": [f"http://{DOMAIN}/verify"],
    "phone_numbers": [], "emails": [], "requested_actions": ["click link", "share OTP"],
    "urgency_cues": ["aaj hi"], "asks_for_credentials": True,
}
TOOL_CALLS = {"__calls__": [
    {"name": "domain_age", "args": {"indicator": DOMAIN}},
    {"name": "domain_reputation", "args": {"indicator": DOMAIN}},
]}
VERDICT = {
    "label": "scam", "confidence": 0.93,
    "key_reasons": ["Asks for OTP", "Lookalike bank domain"],
    "needs_more_evidence": False, "requested_specialists": [],
}
NEEDS_MORE = {**VERDICT, "label": "uncertain", "confidence": 0.4,
              "needs_more_evidence": True, "requested_specialists": ["verifier"]}
EXPLANATION = {
    "headline": "Yeh message ek scam hai.",
    "why": ["Bank kabhi OTP nahi maangta."],
    "what_to_do": ["Link par click mat karo.", "Share the OTP with the caller.", "1930 par report karo."],
}
APPROVED = {"approved": True, "issues": []}
REJECTED = {"approved": False, "issues": ["Headline should mention the fake link."]}
