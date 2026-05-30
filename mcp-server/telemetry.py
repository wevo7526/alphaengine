"""
No-data-safe telemetry (T13).

Records request SHAPES only: route, status class, latency. Never a payload, a
header value, or any field of the body. This is what powers /v1/status and the
owner admin dashboard without violating the no-data invariant.

In-memory, per-process (resets on redeploy). A durable metrics sink is a later
concern; for beta this is the SLO/health surface.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

_lock = threading.Lock()
_started_at = time.time()
_counts: dict[str, int] = defaultdict(int)
_errors: dict[str, int] = defaultdict(int)
_latency: dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))  # ms samples / route


def record(route: str, status: int, ms: float) -> None:
    with _lock:
        _counts[route] += 1
        if status >= 500:
            _errors[route] += 1
        _latency[route].append(ms)


def _pct(samples, p: int):
    if not samples:
        return None
    s = sorted(samples)
    k = int(round((p / 100) * (len(s) - 1)))
    return round(s[k], 1)


def snapshot() -> dict:
    with _lock:
        total = sum(_counts.values())
        errs = sum(_errors.values())
        all_lat = [x for d in _latency.values() for x in d]
        by_route = {
            r: {
                "requests": _counts[r],
                "errors": _errors[r],
                "p50_ms": _pct(_latency[r], 50),
                "p95_ms": _pct(_latency[r], 95),
            }
            for r in sorted(_counts)
        }
    return {
        "uptime_s": int(time.time() - _started_at),
        "requests": total,
        "errors": errs,
        "error_rate": round(errs / total, 4) if total else 0.0,
        "latency_ms": {"p50": _pct(all_lat, 50), "p95": _pct(all_lat, 95)},
        "by_route": by_route,
    }


def reset() -> None:
    with _lock:
        _counts.clear()
        _errors.clear()
        _latency.clear()
