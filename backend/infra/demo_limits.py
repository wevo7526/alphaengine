"""
Demo-desk model-run cap.

The Demo Desk is open to anyone with no login (anonymous X-Demo-Id identity),
and cookies persist their workspace. But the agent pipeline costs real LLM
tokens, so anonymous *model runs* (full analyses) are capped per demo id per
UTC day. Everything else on the desk (browsing, portfolio, memos, macro) is
unrestricted.

In-memory daily counter keyed by (demo_id, UTC date). Resets at UTC midnight
and on redeploy; that is acceptable for the beta (a redeploy only ever grants a
few extra runs, never fewer). A durable per-id counter (DB/Redis) is a later
hardening step if abuse appears.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

DEMO_DAILY_RUN_LIMIT = 2

_lock = threading.Lock()
_counts: dict[tuple[str, str], int] = {}  # (demo_id, yyyy-mm-dd) -> count


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def demo_runs_used(demo_user_id: str) -> int:
    with _lock:
        return _counts.get((demo_user_id, _today()), 0)


def reset() -> None:
    """Clear all demo-run counters (test helper)."""
    with _lock:
        _counts.clear()


def consume_demo_run(keys, limit: int = DEMO_DAILY_RUN_LIMIT) -> dict:
    """
    Try to consume one daily model run across ALL of `keys` (a str or a list).

    Pass both the demo id and a client-IP key, e.g. ["demo:<id>", "ip:1.2.3.4"].
    If ANY key is already at the limit, the run is denied and no counter is
    incremented; otherwise every key is incremented. Capping on IP as well as
    the client-generated demo id stops a visitor from rotating ids to get
    unlimited free model runs. Real accounts are never passed here.

    Returns {allowed, used, limit, remaining} where `used` is the max across keys.
    """
    if isinstance(keys, str):
        keys = [keys]
    day = _today()
    with _lock:
        used = max((_counts.get((k, day), 0) for k in keys), default=0)
        if used >= limit:
            return {"allowed": False, "used": used, "limit": limit, "remaining": 0}
        for k in keys:
            _counts[(k, day)] = _counts.get((k, day), 0) + 1
        used += 1
        return {"allowed": True, "used": used, "limit": limit, "remaining": limit - used}
