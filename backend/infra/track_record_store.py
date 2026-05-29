"""
DB-backed tamper-evident track record (Build Plan §3.3).

Bridges the pure `quant.track_record` hash-chain primitives to the
`signal_scores` rows and the `track_record_anchors` table. `anchor` commits
the current chain head; `verify` recomputes and compares to the most recent
anchor — a mismatch means a historical scored signal was altered, reordered,
or deleted.
"""

from __future__ import annotations

import logging

from sqlalchemy import select, desc

from db.database import async_session
from db.models import SignalScoreRecord, TrackRecordAnchor, gen_uuid
from quant.track_record import chain, head_hash, verify_chain

logger = logging.getLogger(__name__)


async def _ordered_scored_rows(user_id: str | None) -> list[dict]:
    """Scored signals in a stable chain order: signal_date asc, then id."""
    async with async_session() as session:
        q = select(SignalScoreRecord)
        if user_id is not None:
            q = q.where(SignalScoreRecord.user_id == user_id)
        q = q.order_by(SignalScoreRecord.signal_date.asc(), SignalScoreRecord.id.asc())
        result = await session.execute(q)
        rows = result.scalars().all()
    out = []
    for r in rows:
        # Only chain rows that have actually been scored (have a forward price).
        if r.price_5d is None and r.price_1d is None and r.price_20d is None:
            continue
        out.append({
            "ticker": r.ticker, "direction": r.direction, "conviction": r.conviction,
            "signal_date": str(r.signal_date) if r.signal_date else None,
            "entry_price": r.entry_price, "price_1d": r.price_1d,
            "price_5d": r.price_5d, "price_20d": r.price_20d,
            "return_1d": r.return_1d, "return_5d": r.return_5d, "return_20d": r.return_20d,
        })
    return out


async def anchor_track_record(user_id: str | None) -> dict:
    """Commit the current chain head as a new append-only anchor."""
    rows = await _ordered_scored_rows(user_id)
    head = head_hash(rows)
    async with async_session() as session:
        prev = await session.execute(
            select(TrackRecordAnchor)
            .where(TrackRecordAnchor.user_id == user_id)
            .order_by(desc(TrackRecordAnchor.anchored_at))
            .limit(1)
        )
        prev_anchor = prev.scalar_one_or_none()
        rec = TrackRecordAnchor(
            id=gen_uuid(), user_id=user_id, n_records=len(rows),
            head_hash=head, prev_anchor_hash=(prev_anchor.head_hash if prev_anchor else None),
        )
        session.add(rec)
        await session.commit()
    logger.info("[track_record] anchored user=%s n=%d head=%s", user_id, len(rows), head[:12])
    return {"head_hash": head, "n_records": len(rows)}


async def verify_track_record(user_id: str | None) -> dict:
    """Recompute the chain and compare to the latest stored anchor."""
    rows = await _ordered_scored_rows(user_id)
    chained = chain(rows)
    async with async_session() as session:
        prev = await session.execute(
            select(TrackRecordAnchor)
            .where(TrackRecordAnchor.user_id == user_id)
            .order_by(desc(TrackRecordAnchor.anchored_at))
            .limit(1)
        )
        anchor = prev.scalar_one_or_none()
    expected = anchor.head_hash if anchor else None
    result = verify_chain(chained, expected_head=expected)
    result["has_anchor"] = anchor is not None
    if anchor is not None:
        result["anchored_n_records"] = anchor.n_records
        # A shrinking record count is itself a tamper signal (deletion).
        result["record_count_ok"] = len(rows) >= anchor.n_records
        result["ok"] = result["ok"] and result["record_count_ok"]
    return result
