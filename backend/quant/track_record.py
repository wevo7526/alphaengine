"""
Tamper-evident track record + point-in-time guard (Build Plan §3.3).

The forward, out-of-sample track record is the most credible sales asset, so
it must be honest:

  - **Hash chain** — each scored signal's fingerprint is chained to the prior
    one's hash (a mini blockchain). Altering, inserting, or deleting any
    historical record changes its hash and breaks the chain from that point
    on. `verify_chain` recomputes and reports the first break; comparing the
    recomputed head to a previously-stored anchor makes silent edits visible.
  - **Point-in-time guard** — `assert_point_in_time` raises if a signal is
    scored against any observation dated before its `generated_at`, so a
    look-ahead bug can never inflate the record.

Pure and deterministic. The hash is over the *immutable* facts of a scored
signal (when it was made, at what price, and the realized forward returns),
so the chain is reproducible from the data.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any


class LookaheadError(Exception):
    """Raised when a signal is scored against pre-`generated_at` data."""


_GENESIS = "0" * 64


def _to_date(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        s = str(v)
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


# Fields that define a scored signal's identity. Anything outside this set
# (display labels, scored_at timestamps) does not affect the chain.
_FINGERPRINT_FIELDS = (
    "ticker", "direction", "conviction", "signal_date", "entry_price",
    "price_1d", "price_5d", "price_20d",
    "return_1d", "return_5d", "return_20d",
)


def record_fingerprint(rec: dict) -> str:
    """Stable hash of a scored signal's immutable facts."""
    payload = {}
    for k in _FINGERPRINT_FIELDS:
        v = rec.get(k)
        if isinstance(v, float):
            v = round(v, 8)
        if isinstance(v, (datetime, date)):
            v = str(v)
        payload[k] = v
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def chain(records: list[dict]) -> list[dict]:
    """Return records (in given order) annotated with prev_hash + record_hash.

    Caller must pass records in a stable order (e.g. by signal_date, then id).
    record_hash = sha256(prev_hash + fingerprint).
    """
    out = []
    prev = _GENESIS
    for rec in records:
        fp = record_fingerprint(rec)
        h = hashlib.sha256((prev + fp).encode("utf-8")).hexdigest()
        out.append({**rec, "prev_hash": prev, "record_hash": h})
        prev = h
    return out


def head_hash(records: list[dict]) -> str:
    """The chain head — a single hash that commits to the entire ordered record."""
    chained = chain(records)
    return chained[-1]["record_hash"] if chained else _GENESIS


def verify_chain(chained_records: list[dict], expected_head: str | None = None) -> dict:
    """Recompute the chain and report integrity.

    Returns {ok, n, broken_at (index|None), head, expected_head, matches_anchor}.
    `broken_at` is the first index whose stored record_hash disagrees with the
    recomputation (tampering / reordering). `matches_anchor` compares the
    recomputed head to a previously-stored anchor (the real tamper signal).
    """
    prev = _GENESIS
    broken_at = None
    for i, rec in enumerate(chained_records):
        fp = record_fingerprint(rec)
        expect = hashlib.sha256((prev + fp).encode("utf-8")).hexdigest()
        if rec.get("record_hash") and rec["record_hash"] != expect:
            broken_at = i
            break
        prev = rec.get("record_hash") or expect
    recomputed_head = prev
    matches_anchor = (expected_head is None) or (recomputed_head == expected_head)
    return {
        "ok": broken_at is None and matches_anchor,
        "n": len(chained_records),
        "broken_at": broken_at,
        "head": recomputed_head,
        "expected_head": expected_head,
        "matches_anchor": matches_anchor,
    }


def assert_point_in_time(signal_date: Any, observation_dates: list[Any], *, label: str = "signal") -> None:
    """Raise LookaheadError if any observation predates the signal date.

    Use when scoring an idea against forward prices: every price observation
    must be dated on or after the signal's `generated_at`/`signal_date`.
    """
    sd = _to_date(signal_date)
    if sd is None:
        return  # can't verify without a signal date; don't false-positive
    for obs in observation_dates:
        od = _to_date(obs)
        if od is not None and od < sd:
            raise LookaheadError(
                f"{label}: observation {od.isoformat()} predates signal_date "
                f"{sd.isoformat()} — look-ahead/point-in-time violation"
            )
