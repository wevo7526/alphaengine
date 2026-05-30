"""Daily price tape: one grouped call persists to Postgres; reads are pure DB.
No live network — the Massive boundary is monkeypatched."""

from __future__ import annotations

import data.massive_client as mc
import data.price_tape as pt
from db.database import init_db
from db.repositories import PriceTapeRepository


async def test_refresh_persists_then_reads_from_db(monkeypatch):
    await init_db()
    # Mock the Massive grouped-tape surface (no network).
    monkeypatch.setattr(mc, "_recent_grouped_prices", lambda *a, **k: {"AAPL": 200.0, "MSFT": 400.0})
    mc._recent_grouped.update(map={"AAPL": 200.0, "MSFT": 400.0}, date="2026-05-28", ts=0.0)
    monkeypatch.setattr(mc, "grouped_daily", lambda d: [
        {"T": "AAPL", "c": 200.0, "v": 1_000_000},
        {"T": "MSFT", "c": 400.0, "v": 2_000_000},
    ])
    pt._last_refresh_ts = 0.0

    n = await pt.refresh_tape(force=True)
    assert n == 2

    # Reads come straight from Postgres — no Massive call.
    prices = await pt.aget_tape_prices(["AAPL", "MSFT", "ZZZ"])
    assert prices["AAPL"] == 200.0
    assert prices["MSFT"] == 400.0
    assert "ZZZ" not in prices  # absent from the tape -> omitted, not faked

    # Idempotent: re-refreshing the same trading day writes nothing new.
    pt._last_refresh_ts = 0.0
    assert await pt.refresh_tape(force=True) == 0
    assert await PriceTapeRepository.latest_date() is not None


async def test_aget_tape_prices_empty_when_no_tape(monkeypatch):
    await init_db()
    # No grouped data available and an empty tape -> {} (never raises, no fake).
    monkeypatch.setattr(mc, "_recent_grouped_prices", lambda *a, **k: {})
    mc._recent_grouped.update(map=None, date=None, ts=0.0)
    pt._last_refresh_ts = 0.0
    out = await pt.aget_tape_prices(["NOPE"])
    assert out == {}
