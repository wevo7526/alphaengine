"""
Bounded TTL cache.

The data clients all rolled their own `dict[key, (timestamp, value)]` caches
with no size limit. Under sustained traffic those caches grow without bound
and eventually trigger OOM kills in small containers.

`TTLCache` enforces:
  - max_entries: hard cap, LRU eviction when full
  - ttl_seconds: per-entry staleness window
  - thread-safe get/put via a lock (data clients are used from both async
    handlers and thread-pool executors)
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Generic, TypeVar

V = TypeVar("V")


class TTLCache(Generic[V]):
    def __init__(self, *, max_entries: int, ttl_seconds: float):
        self._max = max_entries
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._data: OrderedDict[str, tuple[float, V]] = OrderedDict()

    def get(self, key: str) -> V | None:
        now = time.time()
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            ts, value = entry
            if now - ts > self._ttl:
                # Stale — drop it so callers see a miss.
                self._data.pop(key, None)
                return None
            # Refresh LRU order.
            self._data.move_to_end(key)
            return value

    def set(self, key: str, value: V) -> None:
        with self._lock:
            self._data[key] = (time.time(), value)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def stats(self) -> dict:
        with self._lock:
            return {"size": len(self._data), "max": self._max, "ttl_seconds": self._ttl}
