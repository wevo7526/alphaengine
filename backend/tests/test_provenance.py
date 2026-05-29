"""Phase 1 — evidence receipts: determinism, dedup, and the content-hash cache.

Build Plan Verification:
  - Determinism: same inputs → same computed receipts.
  - Cache reuse: re-running the same query reuses evidence by content_hash
    (no duplicate paid calls).
"""

import pytest

from provenance import (
    content_hash, computed_receipt, source_receipt, FactSheet, EvidenceRepository,
)


def test_content_hash_is_deterministic_under_float_jitter():
    # 0.1 + 0.2 != 0.3 in float, but the canonicalizer collapses the jitter.
    assert content_hash("m", {"a": 0.1 + 0.2}) == content_hash("m", {"a": 0.3})


def test_computed_receipt_stable_hash():
    a = computed_receipt("AAPL P/E", 32.59, formula_ref="data.yahoo.fundamentals", ticker="AAPL")
    b = computed_receipt("AAPL P/E", 32.59, formula_ref="data.yahoo.fundamentals", ticker="AAPL")
    assert a["content_hash"] == b["content_hash"]


def test_source_receipt_whitespace_normalized_dedup():
    a = source_receipt("sec", "0001-23-456", "Risk factors  changed   materially.")
    b = source_receipt("sec", "0001-23-456", "Risk factors changed materially.")
    assert a["content_hash"] == b["content_hash"]


def test_factsheet_dedups_and_assigns_stable_ids():
    fs = FactSheet()
    r = computed_receipt("VIX", 25.78, formula_ref="data.fred.get_macro_snapshot", source_name="fred")
    n1 = fs.add(r)
    n2 = fs.add(dict(r))  # same content_hash → same id
    assert n1 == n2 == 1
    n3 = fs.add(source_receipt("sec", "X", "passage"))
    assert n3 == 2 and len(fs) == 2
    assert fs.valid_ids == {1, 2}


@pytest.mark.asyncio
async def test_upsert_dedup_is_the_cache():
    """Re-running the same query upserts to the same evidence ids."""
    from db.database import init_db
    await init_db()
    recs = [
        source_receipt("sec", "acc-cache-test", "Going concern language added."),
        computed_receipt("MSFT P/E", 30.1, formula_ref="data.yahoo.fundamentals", ticker="MSFT"),
    ]
    m1 = await EvidenceRepository.upsert_many(recs, user_id="u-test")
    m2 = await EvidenceRepository.upsert_many(recs, user_id="u-test")
    assert m1 == m2 and len(m1) == 2


@pytest.mark.asyncio
async def test_claim_links_round_trip():
    from db.database import init_db
    await init_db()
    rec = computed_receipt("NVDA beta", 1.7, formula_ref="quant.factors.beta", ticker="NVDA")
    ids = await EvidenceRepository.upsert_many([rec], user_id="u-test")
    ev_id = next(iter(ids.values()))
    n = await EvidenceRepository.link_claims("memo-xyz", [("trade_idea:NVDA:beta", ev_id)])
    rows = await EvidenceRepository.get_for_memo("memo-xyz")
    assert n == 1 and len(rows) == 1
    assert rows[0]["claim_refs"] == ["trade_idea:NVDA:beta"]
