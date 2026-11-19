"""Runtime settings, read once from environment variables (see .env.example)."""

import os
from pathlib import Path

# Any LiteLLM model string; "ollama_chat/..." keeps everything on this machine.
# 3B by default: a 7-8B model (~5 GB) makes an 8 GB M1 swap and freeze.
MODEL = os.getenv("SAFESPEAK_MODEL", "ollama_chat/qwen2.5:3b")
OLLAMA_API_BASE = os.getenv("OLLAMA_API_BASE", "http://localhost:11434")

# Every model reply is short JSON (~100-300 tokens). The caps stop a runaway
# generation from hanging the pipeline.
MAX_OUTPUT_TOKENS = 700
LLM_TIMEOUT_SECONDS = 180

LOG_PATH = Path(os.getenv("SAFESPEAK_LOG_PATH", "logs/trace.jsonl"))

# Input guardrail limits.
MAX_MESSAGE_CHARS = 4000

# Tool data (RDAP answers, blocklist feeds) is cached here so repeated
# checks and offline demos do not hit the network.
CACHE_DIR = Path(os.getenv("SAFESPEAK_CACHE_DIR", "data/cache"))
FEED_TTL_HOURS = 24
RDAP_TTL_HOURS = 24 * 7

# Retrieval knowledge base: labelled past cases. Development data only;
# test_real.csv is refused by the index (it is the held-out test set).
RETRIEVAL_CORPUS = Path(os.getenv("SAFESPEAK_RETRIEVAL_CORPUS", "data/dev_synthetic.csv"))

# Correlation memory: indicators (domains, phone numbers) of earlier cases,
# never message text. Local file, git-ignored.
CASE_HISTORY_PATH = Path(os.getenv("SAFESPEAK_CASE_HISTORY", "data/case_history.jsonl"))

# Where the run monitor and the A2A server listen. Local only by default,
# because messages may hold OTPs and account numbers. For a deployment, set
# the host to 0.0.0.0 ONLY behind HTTPS and a login: neither server has one.
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
UI_HOST = os.getenv("SAFESPEAK_UI_HOST", "127.0.0.1")
UI_PORT = int(os.getenv("SAFESPEAK_UI_PORT", "8765"))
A2A_HOST = os.getenv("SAFESPEAK_A2A_HOST", "127.0.0.1")
A2A_PORT = int(os.getenv("SAFESPEAK_A2A_PORT", "8010"))
# The address other agents use to reach the A2A server, written into its
# agent card (e.g. https://safespeak.example.com when behind a proxy).
_local_a2a = A2A_HOST if A2A_HOST in LOCAL_HOSTS else "127.0.0.1"
A2A_PUBLIC_URL = os.getenv("SAFESPEAK_A2A_PUBLIC_URL", f"http://{_local_a2a}:{A2A_PORT}").rstrip("/")


def exposure_warning(host: str) -> str | None:
    """A warning to print when a server will be reachable from other machines."""
    if host in LOCAL_HOSTS:
        return None
    return (f"WARNING: listening on {host}, reachable from other machines. There is no login: "
            "put it behind HTTPS and authentication before real messages reach it.")
