"""Shared crew setup: local model only, telemetry off, typed JSON output.

Import this before crewai: the environment switches must be set first.
"""

import os

os.environ.setdefault("OTEL_SDK_DISABLED", "true")  # nothing leaves this machine
os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")

from crewai import LLM  # noqa: E402

from safespeak import config  # noqa: E402


def local_llm() -> LLM:
    """The same Ollama model as the live service, through its local OpenAI-style API."""
    name = config.MODEL.split("/", 1)[-1]
    return LLM(model=f"openai/{name}", base_url=f"{config.OLLAMA_API_BASE}/v1", api_key="local", temperature=0.2)
