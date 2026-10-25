"""Tiny file cache with a time-to-live, shared by both tools."""

import time
from pathlib import Path

from safespeak import config


def cache_path(*parts: str) -> Path:
    path = config.CACHE_DIR.joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def is_fresh(path: Path, ttl_hours: float) -> bool:
    return path.exists() and (time.time() - path.stat().st_mtime) < ttl_hours * 3600
