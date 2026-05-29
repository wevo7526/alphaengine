"""
Persistence + content-hash cache for evidence receipts.

`upsert_many` is the cache win: receipts already present (by content_hash)
are not re-inserted, so re-running the same query reuses evidence rather than
duplicating paid fetches. `get_by_hashes` lets the data layer answer
"have I already retrieved this?" before spending an API call.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from db.database import async_session
from db.models import EvidenceRecord, ClaimEvidenceRecord, gen_uuid

logger = logging.getLogger(__name__)


def _parse_iso(s) -> datetime | None:
    if not s:
        return None
    if isinstance(s, datetime):
        return s
    try:
        return datetime.fromisoformat(str(s))
    except ValueError:
        return None


def _receipt_to_row(receipt: dict, user_id: str | None) -> dict:
    """Map an in-memory receipt dict onto EvidenceRecord columns."""
    return {
        "kind": receipt.get("kind"),
        "source_name": receipt.get("source_name"),
        "source_ref": receipt.get("source_ref"),
        "passage": receipt.get("passage"),
        "retrieved_at": _parse_iso(receipt.get("retrieved_at")) or datetime.now(timezone.utc),
        "metric": receipt.get("metric"),
        "value_json": receipt.get("value"),
        "inputs_json": receipt.get("inputs"),
        "formula_ref": receipt.get("formula_ref"),
        "content_hash": receipt.get("content_hash"),
        "ticker": receipt.get("ticker"),
        "user_id": user_id,
    }


class EvidenceRepository:
    @staticmethod
    async def upsert_many(receipts: list[dict], user_id: str | None = None) -> dict[str, str]:
        """Persist receipts, deduplicating by content_hash.

        Returns {content_hash: evidence_id} for every receipt (existing or
        newly inserted) so callers can link claims to the canonical rows.
        Never raises — provenance persistence must not break a memo.
        """
        if not receipts:
            return {}
        # Dedup the incoming batch by hash first.
        by_hash: dict[str, dict] = {}
        for r in receipts:
            h = r.get("content_hash")
            if h and h not in by_hash:
                by_hash[h] = r
        hashes = list(by_hash.keys())
        out: dict[str, str] = {}
        try:
            async with async_session() as session:
                # Which hashes already exist?
                existing = await session.execute(
                    select(EvidenceRecord.content_hash, EvidenceRecord.id)
                    .where(EvidenceRecord.content_hash.in_(hashes))
                )
                for h, rid in existing.all():
                    out[h] = rid
                to_insert = [
                    _receipt_to_row(by_hash[h], user_id)
                    for h in hashes if h not in out
                ]
                for row in to_insert:
                    # Assign the id explicitly: the column default (gen_uuid)
                    # is only applied at flush, so reading rec.id before commit
                    # would yield None and break the {hash: id} return map.
                    rec = EvidenceRecord(id=gen_uuid(), **row)
                    session.add(rec)
                    out[row["content_hash"]] = rec.id
                await session.commit()
        except Exception as e:
            logger.warning(f"[provenance] upsert_many failed (non-fatal): {e}")
        return out

    @staticmethod
    async def get_by_hashes(hashes: list[str]) -> dict[str, dict]:
        """Return {content_hash: receipt-shaped dict} for cached lookups."""
        if not hashes:
            return {}
        out: dict[str, dict] = {}
        try:
            async with async_session() as session:
                result = await session.execute(
                    select(EvidenceRecord).where(EvidenceRecord.content_hash.in_(hashes))
                )
                for r in result.scalars().all():
                    out[r.content_hash] = {
                        "id": r.id,
                        "kind": r.kind,
                        "source_name": r.source_name,
                        "source_ref": r.source_ref,
                        "passage": r.passage,
                        "metric": r.metric,
                        "value": r.value_json,
                        "inputs": r.inputs_json,
                        "formula_ref": r.formula_ref,
                        "content_hash": r.content_hash,
                        "ticker": r.ticker,
                    }
        except Exception as e:
            logger.warning(f"[provenance] get_by_hashes failed (non-fatal): {e}")
        return out

    @staticmethod
    async def get_by_source_ref(source_name: str, source_ref: str) -> list[dict]:
        """Return cached receipts for a given (source_name, source_ref).

        Used as the permanent filing-section cache: filings are immutable, so
        a section keyed by `{accession}:{section}` need only be fetched once,
        ever. A hit here means zero metered API calls on re-runs.
        """
        if not source_ref:
            return []
        try:
            async with async_session() as session:
                result = await session.execute(
                    select(EvidenceRecord).where(
                        EvidenceRecord.source_name == source_name,
                        EvidenceRecord.source_ref == source_ref,
                    )
                )
                return [
                    {
                        "id": r.id, "kind": r.kind, "source_name": r.source_name,
                        "source_ref": r.source_ref, "passage": r.passage,
                        "content_hash": r.content_hash, "ticker": r.ticker,
                    }
                    for r in result.scalars().all()
                ]
        except Exception as e:
            logger.warning(f"[provenance] get_by_source_ref failed (non-fatal): {e}")
            return []

    @staticmethod
    async def link_claims(memo_id: str, links: list[tuple[str, str]]) -> int:
        """Persist claim→evidence links. `links` is [(claim_ref, evidence_id)].

        Returns the number of links written. Never raises.
        """
        if not memo_id or not links:
            return 0
        try:
            async with async_session() as session:
                for claim_ref, evidence_id in links:
                    if not evidence_id:
                        continue
                    session.add(ClaimEvidenceRecord(
                        memo_id=memo_id,
                        claim_ref=claim_ref,
                        evidence_id=evidence_id,
                    ))
                await session.commit()
            return len(links)
        except Exception as e:
            logger.warning(f"[provenance] link_claims failed (non-fatal): {e}")
            return 0

    @staticmethod
    async def get_for_memo(memo_id: str) -> list[dict]:
        """Return every evidence row cited by a memo, with its claim_refs."""
        if not memo_id:
            return []
        try:
            async with async_session() as session:
                links = await session.execute(
                    select(ClaimEvidenceRecord).where(ClaimEvidenceRecord.memo_id == memo_id)
                )
                link_rows = links.scalars().all()
                ev_ids = list({l.evidence_id for l in link_rows})
                if not ev_ids:
                    return []
                ev = await session.execute(
                    select(EvidenceRecord).where(EvidenceRecord.id.in_(ev_ids))
                )
                ev_by_id = {r.id: r for r in ev.scalars().all()}
                claims_by_ev: dict[str, list[str]] = {}
                for l in link_rows:
                    claims_by_ev.setdefault(l.evidence_id, []).append(l.claim_ref)
                out = []
                for eid, r in ev_by_id.items():
                    out.append({
                        "id": r.id,
                        "kind": r.kind,
                        "source_name": r.source_name,
                        "source_ref": r.source_ref,
                        "passage": r.passage,
                        "metric": r.metric,
                        "value": r.value_json,
                        "formula_ref": r.formula_ref,
                        "ticker": r.ticker,
                        "claim_refs": claims_by_ev.get(eid, []),
                    })
                return out
        except Exception as e:
            logger.warning(f"[provenance] get_for_memo failed (non-fatal): {e}")
            return []
