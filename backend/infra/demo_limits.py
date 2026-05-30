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


def consume_demo_run(demo_user_id: str, limit: int = DEMO_DAILY_RUN_LIMIT) -> dict:
    """
    Try to consume one daily model run for a demo identity.

    Returns {allowed, used, limit, remaining}. When not allowed, the caller
    should 429 and point the user at a free trial. Only call this for demo
    identities (auth.is_demo_user); real accounts are never capped here.
    """
    key = (demo_user_id, _today())
    with _lock:
        used = _counts.get(key, 0)
        if used >= limit:
            return {"allowed": False, "used": used, "limit": limit, "remaining": 0}
        _counts[key] = used + 1
        return {"allowed": True, "used": used + 1, "limit": limit, "remaining": limit - (used + 1)}
