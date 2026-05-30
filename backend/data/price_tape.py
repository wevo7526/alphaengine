"""
Daily price tape — the $0 pricing layer.

One grouped Massive call per day fetches the whole US market's daily closes;
we persist them to Postgres (DailyPriceTapeRecord). Every price read after
that — portfolio marks, the orchestrator's strategist prefetch, EOD
snapshots — reads the DB, so we hit Massive's rate-limited API ~once/day
instead of once per ticker per request. This is what makes the free tier
usable and what keeps the portfolio marking even when the live API is
throttled.

Refresh is decoupled from reads: reads are pure DB lookups (`aget_tape_prices`)
and never block on the network; the tape advances via `refresh_tape()`
(startup hook, the /api/price-tape/refresh cron endpoint, or lazily on a cold
DB). Throttled so it can never hammer Massive.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import date

logger = logging.getLogger(__name__)

_REFRESH_THROTTLE_S = 7200.0  # at most one network refresh attempt / 2h
_last_refresh_ts = 0.0
_refresh_lock = asyncio.Lock()


async def refresh_tape(force: bool = False) -> int:
    """Fetch the most-recent SETTLED grouped tape (1 Massive call, cached) and
    persist it. Skips the write when the DB already has that trading day.
    Throttled to once / 2h unless `force`. Returns rows written (0 if current
    / throttled / failed). Never raises.
    """
    global _last_refresh_ts
    try:
        from db.repositories import PriceTapeRepository
        from data import massive_client

        async with _refresh_lock:
            now = time.monotonic()
            if not force and _last_refresh_ts and (now - _last_refresh_ts) < _REFRESH_THROTTLE_S:
                return 0
            _last_refresh_ts = now

        loop = asyncio.get_running_loop()
        # Walks to the most-recent settled trading day + caches it in-process.
        tape = await loop.run_in_executor(None, massive_client._recent_grouped_prices)
        d = massive_client._recent_grouped.get("date")
        if not tape or not d:
            return 0
        td = date.fromisoformat(d)

        latest = await PriceTapeRepository.latest_date()
        if latest is not None and latest >= td:
            return 0  # DB already has this (or a newer) settled day

        # Re-read the raw grouped bars (cached — no extra call) to capture
        # volume too, so the tape can also serve screening later.
        raw = massive_client.grouped_daily(d)
        rows: list[dict] = []
        for bar in raw or []:
            t = bar.get("T")
            c = bar.get("c")
            if not t or c is None:
                continue
            v = bar.get("v")
            rows.append({
                "ticker": str(t).upper(),
                "close": float(c),
                "volume": float(v) if v is not None else None,
            })
        n = await PriceTapeRepository.upsert_rows(rows, td)
        logger.info("[price_tape] persisted %d tickers for %s", n, td)
        return n
    except Exception as e:  # noqa: BLE001 — pricing must never crash a request
        logger.warning(f"[price_tape] refresh failed: {e}")
        return 0


async def aget_tape_prices(tickers) -> dict[str, float]:
    """{TICKER: latest close} for `tickers`, read from the persisted tape.

    Pure DB read — no Massive call at request time. On a completely cold tape
    (nothing found) it triggers ONE refresh, then reads again. After the first
    refresh of the day, every call is free.
    """
    from db.repositories import PriceTapeRepository

    out = await PriceTapeRepository.prices_for(tickers)
    if out:
        return out
    # Cold DB (or none of these tickers seen) — one refresh, then re-read.
    await refresh_tape()
    return await PriceTapeRepository.prices_for(tickers)
