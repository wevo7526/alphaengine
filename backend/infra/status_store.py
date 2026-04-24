"""
Concurrency-safe replacement for the global `_analysis_status` dict in main.py.

The previous implementation:
  - mutated a module-level dict from multiple coroutines (race: "dictionary
    changed size during iteration")
  - used `hash(query + str(id(request)))` as key, so identical queries from
    retries got different ids — entries were never deduped or replaced
  - evicted by timestamp but only counted "start time"; a hung request never
    aged out

This module exposes an `AnalysisStatusStore` with:
  - asyncio.Lock around all mutations
  - LRU + TTL eviction on every write
  - `heartbeat` support so long analyses age out only when truly stale
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any


class AnalysisStatusStore:
    def __init__(self, *, max_entries: int = 200, ttl_seconds: float = 3600):
        self._max = max_entries
        self._ttl = ttl_seconds
        self._data: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def set(self, key: str, payload: dict[str, Any]) -> None:
        now = time.time()
        async with self._lock:
            entry = {**payload, "_ts": now}
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = entry
            self._evict_locked(now)

    async def heartbeat(self, key: str) -> None:
        """Mark an in-progress entry as still alive so TTL eviction doesn't reap it."""
        now = time.time()
        async with self._lock:
            entry = self._data.get(key)
            if entry is not None:
                entry["_ts"] = now
                self._data.move_to_end(key)

    async def get(self, key: str) -> dict[str, Any] | None:
        async with self._lock:
            entry = self._data.get(key)
            return dict(entry) if entry else None

    async def pop(self, key: str) -> dict[str, Any] | None:
        async with self._lock:
            return self._data.pop(key, None)

    def _evict_locked(self, now: float) -> None:
        # Drop TTL-expired entries first.
        stale = [k for k, v in self._data.items() if now - v.get("_ts", now) > self._ttl]
        for k in stale:
            self._data.pop(k, None)
        # Enforce size cap via LRU eviction.
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def snapshot_stats(self) -> dict:
        return {"size": len(self._data), "max": self._max, "ttl_seconds": self._ttl}
