"""Runtime settings, read once from environment variables (see .env.example)."""

import os
from pathlib import Path

# Any LiteLLM model string; "ollama_chat/..." keeps everything on this machine.
# 3B by default: a 7-8B model (~5 GB) makes an 8 GB M1 swap and freeze.
MODEL = os.getenv("SAFESPEAK_MODEL", "ollama_chat/qwen2.5:3b")
OLLAMA_API_BASE = os.getenv("OLLAMA_API_BASE", "http://localhost:11434")

LOG_PATH = Path(os.getenv("SAFESPEAK_LOG_PATH", "logs/trace.jsonl"))

# Input guardrail limits.
MAX_MESSAGE_CHARS = 4000

# Tool data (RDAP answers, blocklist feeds) is cached here so repeated
# checks and offline demos do not hit the network.
CACHE_DIR = Path(os.getenv("SAFESPEAK_CACHE_DIR", "data/cache"))
FEED_TTL_HOURS = 24
RDAP_TTL_HOURS = 24 * 7
