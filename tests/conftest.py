"""Shared fixtures: isolated trace file and an offline, pre-seeded tool cache.

The MCP server runs as a real subprocess in these tests. It reads
SAFESPEAK_CACHE_DIR, finds fresh cached RDAP answers and blocklist feeds,
and so never touches the network.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from safespeak import config
from safespeak.observability.tracer import tracer
from tests.fake_llm import DOMAIN

BLOCKLISTED = "evil-login.example-phish.com"


@pytest.fixture(autouse=True)
def trace_file(tmp_path, monkeypatch):
    path = tmp_path / "trace.jsonl"
    monkeypatch.setattr(tracer, "path", path)
    return path


@pytest.fixture(autouse=True)
def tool_cache(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    (cache / "rdap").mkdir(parents=True)
    (cache / "feeds").mkdir()
    ten_days_ago = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    record = {"events": [{"eventAction": "registration", "eventDate": ten_days_ago}]}
    (cache / "rdap" / f"{DOMAIN}.json").write_text(json.dumps(record))
    (cache / "rdap" / "hdfcbank.com.json").write_text(
        json.dumps({"events": [{"eventAction": "registration", "eventDate": "1997-04-10T04:00:00Z"}]})
    )
    (cache / "rdap" / "never-registered.in.json").write_text("null")
    (cache / "feeds" / "openphish.txt").write_text(f"https://{BLOCKLISTED}/signin\n")
    (cache / "feeds" / "phishing_database.txt").write_text("other-bad.example.org\n")
    monkeypatch.setenv("SAFESPEAK_CACHE_DIR", str(cache))  # for the MCP subprocess
    monkeypatch.setattr(config, "CACHE_DIR", cache)       # for in-process unit tests
    return cache
