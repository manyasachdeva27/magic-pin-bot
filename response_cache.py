"""
response_cache.py — Cache LLM responses for determinism.

Keyed by (prompt_version, model, canonical fact sheet hash).
Temperature=0 is necessary but not sufficient; the cache guarantees determinism.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from config import cache_key

log = logging.getLogger("vera")

# TTL in seconds (covers the full test window)
_CACHE_TTL = 600  # 10 minutes


class ResponseCache:
    """Simple in-memory cache for LLM responses."""

    def __init__(self):
        self._cache: dict[str, tuple[dict, float]] = {}  # key -> (response, timestamp)

    def get(self, fact_sheet_text: str) -> Optional[dict]:
        """Look up a cached response. Returns None on miss."""
        key = cache_key(fact_sheet_text)
        entry = self._cache.get(key)
        if entry is None:
            return None

        response, ts = entry
        if time.time() - ts > _CACHE_TTL:
            del self._cache[key]
            return None

        log.debug("cache_hit key=%s", key[:16])
        return response

    def put(self, fact_sheet_text: str, response: dict):
        """Store a response in the cache."""
        key = cache_key(fact_sheet_text)
        self._cache[key] = (response, time.time())
        log.debug("cache_put key=%s", key[:16])

    def wipe(self):
        """Clear cache on teardown."""
        self._cache.clear()
