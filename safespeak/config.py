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
