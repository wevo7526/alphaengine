"""
Filing ingestion orchestration (Build Plan §2.1a) — Firecrawl-first.

Pipeline for one ticker:
  1. Resolve the latest + prior comparable filing (1 sec-api listing call —
     the only reliable way to get the dated pair).
  2. For each filing, get the target section text:
       a. evidence-store cache by `{accession}:{section}` (0 cost, permanent —
          filings are immutable), else
       b. Firecrawl scrape of the public filing HTML + our section parser
          (0 sec-api cost — the heavy fetch runs on Firecrawl), else
       c. sec-api ExtractorApi fallback (1 sec-api call).
  3. Deterministic filing_change_score; optional Haiku categorization.
  4. Build the typed NLPSignal + changed-passage source receipts.

Every live sec-api call is metered through `SecBudget` (hard per-process
ceiling). Disabled entirely unless `settings.FILING_NLP_ENABLED`. All
external dependencies are injectable so tests run with zero network.
"""

from __future__ import annotations

import logging

from config import settings

logger = logging.getLogger(__name__)


class SecBudget:
    """Hard per-process ceiling on live sec-api calls.

    Not a true daily budget (resets on restart), but combined with the
    permanent evidence-store cache and FILING_NLP_MAX_NAMES it bounds spend
    on the user's scarce free-tier quota. Logs remaining on every consume.
    """

    _used = 0

    @classmethod
    def remaining(cls) -> int:
        return max(0, int(settings.SEC_CALL_BUDGET) - cls._used)

    @classmethod
    def consume(cls, n: int = 1) -> bool:
        if cls.remaining() < n:
            logger.warning("[filing_ingest] sec-api budget exhausted (%d used)", cls._used)
            return False
        cls._used += n
        logger.info("[filing_ingest] sec-api call (%d used, %d left)", cls._used, cls.remaining())
        return True

    @classmethod
    def reset(cls) -> None:
        cls._used = 0


def _filing_url(f: dict) -> str | None:
    """Best public document URL from a sec-api filing record."""
    for k in ("linkToFilingDetails", "linkToHtml", "linkToTxt", "linkToFilingIndex"):
        v = f.get(k)
        if v:
            return v
    return None


async def _list_latest_prior(ticker: str, form: str, sec_client) -> list[dict]:
    """Resolve the two most-recent filings of `form` (1 sec-api call)."""
    if not SecBudget.consume(1):
        return []
    try:
        data = await sec_client.aget_recent_filings(ticker, form, 2)
    except Exception as e:
        logger.warning("[filing_ingest] listing failed for %s/%s: %s", ticker, form, e)
        return []
    out = []
    for f in (data.get("filings") or [])[:2]:
        out.append({
            "accession": f.get("accessionNo") or f.get("accessionNumber") or "unknown",
            "url": _filing_url(f),
            "filed_at": f.get("filedAt"),
            "form": f.get("formType") or form,
        })
    return out


async def _section_text(
    ticker: str, filing: dict, section: str, form: str,
    *, sec_client, firecrawl, evidence_repo,
) -> tuple[str, dict | None, str]:
    """Get one section's text. Returns (text, cache_receipt|None, source).

    `source` ∈ {"cache", "firecrawl", "sec-api", "none"} for the audit trail.
    Persists a cache receipt keyed `sec-section:{accession}:{section}` so the
    next run reads it for free.
    """
    from agents.nlp.sections import extract_section_from_text
    from provenance import source_receipt

    accession = filing.get("accession") or "unknown"
    url = filing.get("url")
    cache_ref = f"sec-section:{accession}:{section}"

    # (a) permanent cache
    try:
        cached = await evidence_repo.get_by_source_ref("sec", cache_ref)
        if cached and (cached[0].get("passage") or "").strip():
            return cached[0]["passage"], None, "cache"
    except Exception as e:
        logger.debug("[filing_ingest] cache lookup failed: %s", e)

    text = ""
    source = "none"
    # (b) Firecrawl scrape of public HTML + our parser
    if url:
        try:
            doc = await firecrawl.ascrape_full(url)
            content = (doc or {}).get("content") or ""
            if content:
                text = extract_section_from_text(content, section)
                if text:
                    source = "firecrawl"
        except Exception as e:
            logger.debug("[filing_ingest] firecrawl scrape failed for %s: %s", url, e)

    # (c) sec-api extraction fallback
    if not text and url and SecBudget.consume(1):
        try:
            import asyncio
            extract = (sec_client.extract_risk_factors if section == "1A"
                       else sec_client.extract_mda)
            text = await asyncio.get_running_loop().run_in_executor(None, extract, url) or ""
            if text:
                source = "sec-api"
        except Exception as e:
            logger.warning("[filing_ingest] sec-api extract failed for %s: %s", url, e)

    cache_receipt = None
    if text:
        # Cache the full section so future runs skip the fetch entirely.
        cache_receipt = source_receipt(
            "sec", cache_ref, text[:20000], ticker=ticker, url=url,
            label=f"{form} §{section} · {ticker} ({accession})",
        )
    return text, cache_receipt, source


async def run_filing_change(
    ticker: str,
    *,
    section: str = "1A",
    form: str | None = None,
    sec_client=None,
    firecrawl=None,
    evidence_repo=None,
    use_llm: bool | None = None,
) -> dict:
    """Full filing-change pass for one ticker. Never raises.

    Returns:
        {ticker, signal: NLPSignal|None, receipts: [dict], cache_receipts: [dict],
         score: dict|None, sources: {latest, prior}, warnings: [str]}
    """
    form = form or settings.FILING_NLP_FORM
    if use_llm is None:
        use_llm = settings.FILING_NLP_LLM

    warnings: list[str] = []
    if not settings.FILING_NLP_ENABLED:
        return {"ticker": ticker, "signal": None, "receipts": [], "cache_receipts": [],
                "score": None, "sources": {}, "warnings": ["filing NLP disabled"]}

    # Lazy real dependencies; tests inject fakes.
    if sec_client is None:
        from data.sec_client import SECDataClient
        sec_client = SECDataClient()
    if firecrawl is None:
        from data import firecrawl_client as firecrawl
    if evidence_repo is None:
        from provenance import EvidenceRepository as evidence_repo

    from agents.nlp.filing_diff import filing_change_score, categorize_changes_llm, build_filing_signal

    filings = await _list_latest_prior(ticker, form, sec_client)
    if len(filings) < 2:
        warnings.append(f"need 2 {form} filings, found {len(filings)}")
        return {"ticker": ticker, "signal": None, "receipts": [], "cache_receipts": [],
                "score": None, "sources": {}, "warnings": warnings}

    latest, prior = filings[0], filings[1]
    cache_receipts: list[dict] = []
    cur_text, cur_cache, cur_src = await _section_text(
        ticker, latest, section, form, sec_client=sec_client, firecrawl=firecrawl, evidence_repo=evidence_repo)
    pri_text, pri_cache, pri_src = await _section_text(
        ticker, prior, section, form, sec_client=sec_client, firecrawl=firecrawl, evidence_repo=evidence_repo)
    for c in (cur_cache, pri_cache):
        if c:
            cache_receipts.append(c)

    score = filing_change_score(cur_text, pri_text, section=section)
    llm_cat = None
    if use_llm and score.get("has_prior") and score.get("change_score", 0) >= 0.18:
        llm_cat = categorize_changes_llm(score, ticker)

    signal, receipts = build_filing_signal(
        ticker, score, llm_categorization=llm_cat,
        accession=latest.get("accession"), filing_url=latest.get("url"),
    )

    return {
        "ticker": ticker,
        "signal": signal,
        "receipts": receipts,
        "cache_receipts": cache_receipts,
        "score": score,
        "sources": {"latest": cur_src, "prior": pri_src},
        "warnings": warnings,
    }
