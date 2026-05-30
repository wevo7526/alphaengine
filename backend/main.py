from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import select, desc
import hashlib
import json
import asyncio
import logging
import os
import sys
import time as _time

from config import settings, validate_startup
from auth import get_user_id, require_user_id
from data.fred_client import FREDDataClient
from data.market_client import MarketDataClient
from data.news_client import NewsDataClient
from data.sec_client import SECDataClient
from db.database import init_db, async_session, ping_db, DB_DIALECT
from db.models import IntelligenceMemoRecord, WatchlistRecord, SignalScoreRecord
from infra.logging_ctx import RequestIdMiddleware, install_logging, get_request_id
from infra.status_store import AnalysisStatusStore
from infra.timeout import RequestTimeoutMiddleware
from infra.user_context import (
    DEFAULT_PORTFOLIO_BASE_USD,
    resolve_portfolio_base,
    resolve_user_context,
)

# Install structured-logging filter before any app logging happens.
logging.basicConfig(level=logging.INFO)
install_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Validate configuration, probe the database, surface problems loudly on boot.

    Fatal misconfigurations (missing required secrets in production) log at
    ERROR level but do not kill the process — we want the /api/health endpoint
    to stay reachable so orchestrators can route traffic away. Non-fatal
    issues like a down database are surfaced via health-check "degraded".
    """
    logger.info(
        f"Starting Alpha Engine — ENV={settings.ENV}, "
        f"PORT={os.environ.get('PORT', 'not set')}, "
        f"DB_DIALECT={DB_DIALECT}"
    )

    startup_errors = validate_startup()
    if startup_errors:
        for err in startup_errors:
            logger.error(f"Startup error: {err}")
        if settings.ENV == "production":
            logger.error(
                "Production startup validation FAILED. /api/health will report "
                "'degraded'. Fix the configuration and redeploy."
            )

    try:
        await init_db()
    except Exception as e:
        logger.error(f"Database init failed (non-fatal, app will start): {e}")

    # Probe the database once so startup logs reflect actual state.
    probe = await ping_db(timeout=3.0)
    if probe["ok"]:
        logger.info(f"Database probe OK (dialect={probe['dialect']})")
    else:
        logger.error(f"Database probe FAILED: {probe.get('error')}")

    # Pre-warm the FRED cache in the background so the first user dashboard
    # load never sits on a cold cache. Fire-and-forget — failures are logged
    # by the underlying client and the in-band request path still works.
    async def _prewarm_macro():
        try:
            from quant.computations import get_macro_time_series
            await asyncio.gather(
                fred_client.aget_macro_snapshot(),
                asyncio.get_running_loop().run_in_executor(None, get_macro_time_series),
            )
            logger.info("Macro cache pre-warmed")
        except Exception as e:
            logger.warning(f"Macro pre-warm failed (non-fatal): {e}")

    asyncio.create_task(_prewarm_macro())

    # Pre-populate the daily price tape (one grouped Massive call -> Postgres)
    # so portfolio marks + pricing read from the DB, not the rate-limited API.
    async def _prewarm_tape():
        try:
            from data import price_tape
            n = await price_tape.refresh_tape()
            logger.info("Price tape pre-warmed (%d tickers)", n)
        except Exception as e:
            logger.warning(f"Price tape pre-warm failed (non-fatal): {e}")

    asyncio.create_task(_prewarm_tape())

    app.state.startup_errors = startup_errors
    yield


app = FastAPI(title="Alpha Engine API", version="2.0.0", lifespan=lifespan)

# Request ID first so every subsequent log line is tagged.
app.add_middleware(RequestIdMiddleware)

# Hard backstop on every non-streaming handler so a stuck dependency
# (FRED, LLM, DB) can never wedge the frontend into perpetual loading.
# Returns 504 after the deadline. Exemptions:
#   /api/analyze/stream — SSE; long-lived by design.
#   /api/analyze        — non-streaming fallback; orchestrator has its
#                         own per-step deadlines totalling ~8 min.
#   /api/backtest/run   — backtests legitimately scan months of bars.
#   /api/morning-report — multi-agent report generation.
app.add_middleware(
    RequestTimeoutMiddleware,
    timeout_seconds=90.0,
    exempt_path_prefixes=(
        "/api/analyze/stream",
        "/api/analyze",
        "/api/backtest/run",
        "/api/morning-report",
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Singleton data clients
fred_client = FREDDataClient()
market_client = MarketDataClient()
news_client = NewsDataClient()
sec_client = SECDataClient()

# Concurrency-safe replacement for the old global _analysis_status dict.
analysis_status = AnalysisStatusStore(max_entries=200, ttl_seconds=3600)


def _stable_query_id(query: str, user_id: str) -> str:
    """
    Deterministic id keyed on (user, query). Retries from the same user
    for the same query land on the same entry instead of piling up.
    """
    h = hashlib.sha1(f"{user_id}|{query}".encode("utf-8")).hexdigest()
    return h[:16]


# === HEALTH CHECK ===

@app.get("/api/health")
async def health_check():
    """
    Liveness + dependency probe.

    Returns 200 {status: "healthy"} when all critical dependencies are OK,
    200 {status: "degraded"} when the app is up but something is wrong
    (DB down, required config missing). Returning 200 on degraded is
    intentional — platform orchestrators should rely on /api/ready (below)
    for traffic-routing decisions, while /api/health tells on-call what
    is broken. A flat 200 "healthy" on a broken app would be worse.
    """
    startup_errors = getattr(app.state, "startup_errors", []) or []
    db = await ping_db(timeout=2.0)

    checks = {
        "database": db,
        "startup_errors": startup_errors,
        "env": settings.ENV,
        "request_id": get_request_id(),
    }
    degraded = bool(startup_errors) or not db["ok"]
    return {"status": "degraded" if degraded else "healthy", "checks": checks}


@app.get("/api/system/info")
async def system_info():
    """
    Live system info for Settings page: dependency keys configured, risk
    parameters in effect, app metadata. No secrets — only presence flags.
    Risk thresholds are read from quant.limits at request time so changes
    via env vars surface immediately without code edits.
    """
    from quant import limits as _limits
    db = await ping_db(timeout=2.0)
    L = _limits.as_dict()

    return {
        "app": {
            "version": app.version,
            "env": settings.ENV,
            "commit": os.environ.get("RAILWAY_GIT_COMMIT_SHA", "")[:8] or None,
        },
        "database": {
            "ok": db["ok"],
            "dialect": db.get("dialect"),
        },
        "data_sources": [
            {"name": "Anthropic (Claude)", "configured": bool(settings.ANTHROPIC_API_KEY), "note": "LLM for all agents"},
            {"name": "FRED (Macro)", "configured": bool(settings.FRED_API_KEY), "note": "13 indicators, 1hr cache"},
            {"name": "Massive (Market)", "configured": bool(settings.MASSIVE_API_KEY), "note": "Price, fundamentals, options, news"},
            {"name": "SEC EDGAR (sec-api.io)", "configured": bool(settings.SEC_API_KEY), "note": "Filings, insider trades, 13F"},
            {"name": "Alpha Vantage", "configured": bool(settings.ALPHA_VANTAGE_KEY), "note": "Analyst targets + ratings (free, 25/day)"},
            {"name": "Firecrawl", "configured": bool(settings.FIRECRAWL_API_KEY), "note": "Web validation (optional)"},
        ],
        "auth": {
            "provider": "Clerk",
            "issuer_configured": bool(settings.CLERK_ISSUER),
        },
        "risk_parameters": [
            {"label": "Max position size", "value": f"{L['max_position_pct']}%", "description": "Hard cap per single position (risk gate + optimizer)"},
            {"label": "Max sector concentration", "value": f"{L['max_sector_pct']}%", "description": "Maximum allocation to one sector"},
            {"label": "Min position size", "value": f"{L['min_position_pct']}%", "description": "Below this, trade is rejected as noise"},
            {"label": "VaR confidence", "value": f"{int(L['var_confidence']*100)}%", "description": "Parametric + Cornish-Fisher + bootstrap CI"},
            {"label": "Marginal VaR block threshold", "value": f"{L['marginal_var_block_pct']}%", "description": "Trade rejected if it adds more than this to portfolio VaR"},
            {"label": "Silent-squeeze guard", "value": f"{int(L['silent_squeeze_threshold']*100)}%", "description": "Refuse fill if size shrinks below this fraction of requested"},
            {"label": "DD circuit breaker (caution / warn / critical)", "value": f"{L['drawdown_caution_pct']}% / {L['drawdown_warn_pct']}% / {L['drawdown_critical_pct']}%", "description": "Tiered drawdown response on real book P&L"},
            {"label": "Liquidity max %ADV / block %ADV", "value": f"{int(L['liquidity_max_pct_of_adv']*100)}% / {int(L['liquidity_block_pct_of_adv']*100)}%", "description": "Position-vs-average-daily-volume gate"},
            {"label": "Optimizer turnover cost", "value": f"{L['optimizer_tx_cost_bps']} bp", "description": "Penalty deducted in mean-variance objective"},
            {"label": "BUY/SELL conviction threshold", "value": "75", "description": "Minimum CIO conviction for GO"},
            {"label": "WATCH conviction threshold", "value": "50", "description": "Minimum conviction for WATCH"},
        ],
    }


@app.get("/api/ready")
async def readiness_check():
    """
    Readiness probe — returns 503 if the app can't serve traffic.

    Use this from Kubernetes/Railway readiness probes. `/api/health` is
    for humans; `/api/ready` is for orchestrators.
    """
    db = await ping_db(timeout=2.0)
    startup_errors = getattr(app.state, "startup_errors", []) or []
    if not db["ok"] or (settings.ENV == "production" and startup_errors):
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "db": db, "startup_errors": startup_errors},
        )
    return {"status": "ready"}


# === AUTH ===

@app.get("/api/auth/me")
async def auth_me(request: Request):
    """
    Session guard. Returns {user_id} if authenticated, 401 otherwise.
    Frontend uses this on every page load to verify session before rendering.
    """
    user_id = require_user_id(request)
    return {"user_id": user_id, "authenticated": True}


async def _resolve_user_limits(user_id: str) -> dict[str, float]:
    """
    Look up the user's risk overrides and merge with platform defaults.
    Returns a flat dict keyed by quant.limits.PARAMS_META field names.

    Failure-safe: any DB error falls back to platform defaults so a risk
    profile lookup glitch can never break trade execution.
    """
    from db.repositories import UserRiskProfileRepository
    from quant.limits import resolve_for_user
    try:
        overrides = await UserRiskProfileRepository.get(user_id)
    except Exception as e:
        logger.warning(f"user risk lookup failed for {user_id}, using defaults: {e}")
        overrides = None
    return resolve_for_user(overrides)


# === USER PROFILE + ONBOARDING ===

class ProfileUpdate(BaseModel):
    """
    Body for PUT /api/me/profile. Every field optional so the onboarding
    wizard can call this incrementally as the user advances through steps.
    """
    full_name: str | None = None
    email: str | None = None
    role: str | None = None
    portfolio_size_usd: float | None = None
    benchmark: str | None = None
    mandate: str | None = None


class OnboardingCompletePayload(ProfileUpdate):
    """Same fields as ProfileUpdate; sets onboarded_at server-side."""
    pass


@app.get("/api/me/profile")
async def get_my_profile(request: Request):
    """
    Return the authenticated user's profile or {profile: null, onboarded: False}
    when no profile exists. SessionGuard uses this to route new users to
    /onboarding.
    """
    from db.repositories import UserProfileRepository
    user_id = require_user_id(request)
    profile = await UserProfileRepository.get(user_id)
    return {
        "profile": profile,
        "onboarded": bool(profile and profile.get("onboarded_at") is not None),
    }


@app.put("/api/me/profile")
async def update_my_profile(payload: ProfileUpdate, request: Request):
    """
    Upsert profile fields. Used during onboarding (per-step save) and from
    Settings later for edits. Does NOT set onboarded_at — use
    /api/me/onboarding/complete for that.
    """
    from db.repositories import UserProfileRepository
    user_id = require_user_id(request)
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    profile = await UserProfileRepository.upsert(user_id, fields)
    return {"profile": profile, "onboarded": bool(profile.get("onboarded_at"))}


@app.post("/api/me/onboarding/complete")
async def complete_onboarding(payload: OnboardingCompletePayload, request: Request):
    """
    Mark the user as onboarded. Sets onboarded_at = now() and persists any
    final field values from the wizard's last step in the same write.
    Idempotent: calling twice is harmless, onboarded_at gets refreshed.
    """
    from db.repositories import UserProfileRepository
    user_id = require_user_id(request)
    fields = {k: v for k, v in payload.model_dump().items() if v is not None}
    profile = await UserProfileRepository.mark_onboarded(user_id, fields)
    return {"profile": profile, "onboarded": True}


# === USER RISK PROFILE — per-user overrides for risk gates ===

@app.get("/api/me/risk")
async def get_my_risk(request: Request):
    """
    Return the merged view of risk gates for this user. Each parameter
    includes its current value, the platform default, and where the
    value comes from (user / env / default). Drives the /risk-config UI.
    """
    from db.repositories import UserRiskProfileRepository
    from quant.limits import merged_view
    user_id = require_user_id(request)
    overrides = await UserRiskProfileRepository.get(user_id)
    return {"parameters": merged_view(overrides)}


@app.patch("/api/me/risk")
async def update_my_risk(payload: dict, request: Request):
    """
    Partial-update risk overrides. Body is {field: value}. Pass {field: null}
    to reset a single field back to the platform default.

    Validation enforces per-field ranges (defined in quant.limits.PARAMS_META)
    and cross-field invariants (drawdown caution < warn < critical). Returns
    HTTP 400 with the list of validation errors if anything is invalid;
    nothing is persisted on validation failure.
    """
    from db.repositories import UserRiskProfileRepository
    from quant.limits import merged_view, validate_overrides
    user_id = require_user_id(request)
    cleaned, errors = validate_overrides(payload or {})
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})
    await UserRiskProfileRepository.upsert(user_id, cleaned)
    overrides = await UserRiskProfileRepository.get(user_id)
    return {"parameters": merged_view(overrides)}


@app.delete("/api/me/risk")
async def reset_my_risk(request: Request):
    """Wipe all user overrides — every gate falls back to the platform default."""
    from db.repositories import UserRiskProfileRepository
    from quant.limits import merged_view
    user_id = require_user_id(request)
    await UserRiskProfileRepository.reset(user_id)
    return {"parameters": merged_view(None)}


# === ANALYSIS ENDPOINTS ===

class AnalyzeRequest(BaseModel):
    query: str
    # Optional follow-up handle. When provided, the orchestrator loads
    # ThreadContext (prior tickers/themes/decision/summary) and the
    # Interpreter classifies the query into one of the seven query_class
    # buckets. The new memo inherits thread_id and bumps sequence_in_thread.
    parent_memo_id: str | None = None


@app.post("/api/analyze")
async def analyze(request: AnalyzeRequest, req: Request):
    """Run the full research desk pipeline on a freeform query."""
    import traceback
    from agents.orchestrator import run_research_desk
    user_id = require_user_id(req)

    query = request.query.strip()
    query_id = _stable_query_id(query, user_id)
    await analysis_status.set(query_id, {"status": "running", "phase": "interpreting"})

    try:
        memo = await run_research_desk(
            query, user_id=user_id, parent_memo_id=request.parent_memo_id,
        )
        result = memo.model_dump(mode="json")

        # Persist to database — wrap so DB errors don't kill the response.
        try:
            async with async_session() as session:
                # When this is a fresh thread (no parent), thread_id is None
                # on the memo object. We backfill it to the memo's own id after
                # insert so single-memo threads are still queryable by thread_id.
                resolved_thread_id = memo.thread_id  # None for fresh
                record = IntelligenceMemoRecord(
                    user_id=user_id,
                    query=memo.query,
                    intent=memo.intent.value if hasattr(memo.intent, "value") else str(memo.intent),
                    title=memo.title,
                    executive_summary=memo.executive_summary,
                    analysis=memo.analysis,
                    key_findings=memo.key_findings,
                    macro_regime=memo.macro_regime,
                    overall_risk_level=memo.overall_risk_level,
                    risk_factors=[rf.model_dump() if hasattr(rf, "model_dump") else rf for rf in memo.risk_factors],
                    trade_ideas=[ti.model_dump() if hasattr(ti, "model_dump") else ti for ti in memo.trade_ideas],
                    portfolio_positioning=memo.portfolio_positioning,
                    hedging_recommendations=memo.hedging_recommendations,
                    tickers_analyzed=memo.tickers_analyzed,
                    themes=memo.themes,
                    lineage=memo.lineage or {},
                    thread_id=resolved_thread_id,
                    parent_memo_id=memo.parent_memo_id,
                    sequence_in_thread=memo.sequence_in_thread,
                    thread_summary=memo.thread_summary,
                    query_class=memo.query_class,
                    # Phase G — claim-level citations
                    citation_index=[
                        c.model_dump() if hasattr(c, "model_dump") else c
                        for c in (memo.citation_index or [])
                    ],
                    coverage=memo.coverage or {},
                    verification_status=memo.verification_status or "unverified",
                )
                session.add(record)
                await session.commit()
                # Backfill thread_id to the new memo's own id when fresh
                if resolved_thread_id is None:
                    record.thread_id = record.id
                    await session.commit()
                result["id"] = record.id
                result["thread_id"] = record.thread_id
                result["parent_memo_id"] = record.parent_memo_id
                result["sequence_in_thread"] = record.sequence_in_thread
                logger.info(
                    f"Memo persisted: {record.id} thread={record.thread_id} "
                    f"seq={record.sequence_in_thread} class={record.query_class} user={user_id}"
                )

                # Phase 1 — persist evidence receipts (content-hash deduped, so
                # this doubles as the cross-query cache) and link each cited
                # claim to its evidence row. Own try: provenance must never
                # break the memo response.
                try:
                    receipts = getattr(memo, "evidence_receipts", None) or []
                    ev_links = getattr(memo, "evidence_links", None) or []
                    if receipts:
                        from provenance import EvidenceRepository
                        hash_to_id = await EvidenceRepository.upsert_many(receipts, user_id=user_id)
                        links = [
                            (l.get("claim_ref"), hash_to_id.get(l.get("content_hash")))
                            for l in ev_links if hash_to_id.get(l.get("content_hash"))
                        ]
                        if links:
                            await EvidenceRepository.link_claims(record.id, links)
                        logger.info(
                            f"[provenance] memo {record.id}: {len(hash_to_id)} evidence rows, "
                            f"{len(links)} claim links"
                        )
                except Exception as ev_err:
                    logger.warning(f"[provenance] evidence persist failed (non-fatal): {ev_err}")
        except Exception as db_err:
            logger.error(f"DB persist failed (non-fatal): {db_err}")

        await analysis_status.set(query_id, {"status": "complete", "phase": "done"})
        return result
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Analysis failed: {e}\n{tb}")
        await analysis_status.set(query_id, {"status": "error", "error": str(e)})
        raise HTTPException(status_code=500, detail=str(e))



@app.get("/api/signals/latest")
async def latest_signals(req: Request, limit: int = 20):
    """Get most recent intelligence memos for the current user."""
    user_id = require_user_id(req)
    try:
        async with async_session() as session:
            query = (
                select(IntelligenceMemoRecord)
                .where(IntelligenceMemoRecord.user_id == user_id)
                .order_by(desc(IntelligenceMemoRecord.created_at))
            )
            result = await session.execute(query.limit(limit))
            records = result.scalars().all()
            memos = [
                {
                    "id": r.id,
                    "query": r.query,
                    "intent": r.intent,
                    "title": r.title,
                    "executive_summary": r.executive_summary,
                    "analysis": r.analysis or "",
                    "key_findings": r.key_findings or [],
                    "macro_regime": r.macro_regime,
                    "overall_risk_level": r.overall_risk_level,
                    "risk_factors": r.risk_factors or [],
                    "trade_ideas": r.trade_ideas or [],
                    "portfolio_positioning": r.portfolio_positioning or "",
                    "hedging_recommendations": r.hedging_recommendations or [],
                    "tickers_analyzed": r.tickers_analyzed or [],
                    "themes": r.themes or [],
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    # Phase G — claim-level citations + verification
                    "citation_index": r.citation_index or [],
                    "coverage": r.coverage or {},
                    "verification_status": r.verification_status or "unverified",
                    # Lineage already lives on the record — expose it so the
                    # frontend's existing LineagePanel keeps working alongside
                    # the new per-claim citation rendering.
                    "lineage": r.lineage or {},
                }
                for r in records
            ]
            return {"memos": memos, "count": len(memos)}
    except Exception as e:
        logger.error(f"Failed to fetch memos: {e}")
        return {"memos": [], "count": 0}


@app.delete("/api/signals/{memo_id}")
async def delete_memo(memo_id: str, req: Request):
    """Delete an intelligence memo by ID. Only the owner can delete."""
    user_id = require_user_id(req)
    async with async_session() as session:
        result = await session.execute(
            select(IntelligenceMemoRecord).where(
                IntelligenceMemoRecord.id == memo_id,
                IntelligenceMemoRecord.user_id == user_id,
            )
        )
        record = result.scalar_one_or_none()
        if not record:
            raise HTTPException(status_code=404, detail="Memo not found")
        await session.delete(record)
        await session.commit()
    return {"deleted": memo_id}


@app.post("/api/signals/flush")
async def flush_signals(req: Request, scope: str = "all"):
    """
    Bulk-delete the authenticated user's intelligence memos.
    `scope`: "all" (default) deletes every memo for this user;
             "stale" deletes memos older than 30 days.
    Strictly user-scoped — cannot affect other users' analyses.
    """
    from sqlalchemy import delete as sql_delete
    from datetime import datetime, timezone, timedelta

    user_id = require_user_id(req)
    if scope not in ("all", "stale"):
        raise HTTPException(status_code=400, detail="scope must be all|stale")

    async with async_session() as session:
        stmt = sql_delete(IntelligenceMemoRecord).where(
            IntelligenceMemoRecord.user_id == user_id
        )
        if scope == "stale":
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            stmt = stmt.where(IntelligenceMemoRecord.created_at < cutoff)
        result = await session.execute(stmt)
        await session.commit()
        deleted = result.rowcount or 0

    logger.info(f"flush_signals: user={user_id} scope={scope} deleted={deleted}")
    return {"deleted": deleted, "scope": scope}


# === DATA ENDPOINTS ===

@app.get("/api/data/macro")
async def macro_dashboard():
    """Consolidated macro endpoint — snapshot + time series in one call.

    Never raises on FRED outage: returns whatever we have (possibly empty)
    along with `fred_status: "ok" | "degraded" | "down"` so the frontend
    can show a banner instead of an error toast.
    """
    from quant.computations import get_macro_time_series
    snapshot: dict = {}
    series: dict = {}
    try:
        snapshot, series = await asyncio.gather(
            fred_client.aget_macro_snapshot(),
            asyncio.get_running_loop().run_in_executor(None, get_macro_time_series),
        )
    except Exception as e:
        # Last-resort safety net — individual paths already swallow their
        # own exceptions, but if something else raises we still return a
        # valid (empty) payload rather than 500ing the dashboard.
        logger.error(f"Macro dashboard partial failure: {e}")

    expected = 13  # MACRO_SERIES length
    if len(snapshot) >= expected * 0.7:
        status = "ok"
    elif snapshot:
        status = "degraded"
    else:
        status = "down"

    return {
        "indicators": snapshot,
        "count": len(snapshot),
        "series": series,
        "fred_status": status,
    }


@app.get("/api/data/macro/snapshot")
async def macro_snapshot_legacy():
    """Legacy endpoint — use /api/data/macro instead."""
    try:
        snapshot = await fred_client.aget_macro_snapshot()
        return {"indicators": snapshot, "count": len(snapshot)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/data/market/{ticker}")
async def market_data(ticker: str, period: str = "3mo"):
    """Price history and fundamentals for a ticker."""
    ticker = ticker.upper()
    try:
        fundamentals, price_history = await asyncio.gather(
            market_client.aget_fundamentals(ticker),
            market_client.aget_price_history(ticker, period=period),
        )
        return {
            "ticker": ticker,
            "fundamentals": fundamentals,
            "price_history": price_history,
            "bars": len(price_history),
        }
    except Exception as e:
        logger.error(f"Market data failed for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/data/market/{ticker}/options")
async def options_data(ticker: str, expiry: str | None = None):
    """Options chain for a ticker."""
    ticker = ticker.upper()
    try:
        chain = await market_client.aget_options_chain(ticker, expiry=expiry)
        return {"ticker": ticker, **chain}
    except Exception as e:
        logger.error(f"Options data failed for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/data/filings/{ticker}")
async def sec_filings(ticker: str, form_type: str = "8-K", limit: int = 5):
    """Recent SEC filings for a ticker."""
    ticker = ticker.upper()
    try:
        filings = await sec_client.aget_recent_filings(ticker, form_type=form_type, limit=limit)
        return {"ticker": ticker, "form_type": form_type, "filings": filings}
    except Exception as e:
        logger.error(f"SEC filings failed for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/data/news/{ticker}")
async def news_feed(ticker: str):
    """Recent news with sentiment data."""
    ticker = ticker.upper()
    try:
        articles, sentiment = await asyncio.gather(
            news_client.aget_ticker_news(ticker, page_size=10),
            news_client.aget_market_sentiment_finnhub(ticker),
        )
        return {
            "ticker": ticker,
            "articles": articles,
            "article_count": len(articles),
            "finnhub_sentiment": sentiment,
        }
    except Exception as e:
        logger.error(f"News feed failed for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/data/events")
async def upcoming_events(
    lookforward_days: int = 30,
    event_types: str = "",
    region: str = "",
):
    """
    Upcoming scheduled macro events from the curated calendar (FOMC, CPI,
    NFP, ECB, OPEC). Filters: comma-separated `event_types` and single `region`.

    Returns {events, n_events, coverage_end_date, lookforward_days, stale}.
    `stale=True` when coverage_end_date is before today (seed needs refresh).
    """
    from data.events import get_upcoming_events, coverage_end_date
    types_list = [t.strip().upper() for t in event_types.split(",") if t.strip()] or None
    region_filter = region.strip().upper() or None
    events = get_upcoming_events(
        lookforward_days=lookforward_days,
        event_types=types_list,
        region=region_filter,
    )
    cov_end = coverage_end_date()
    today = datetime.now(timezone.utc).date()
    return {
        "events": events,
        "n_events": len(events),
        "coverage_end_date": cov_end.isoformat() if cov_end else None,
        "stale": bool(cov_end and cov_end < today),
        "lookforward_days": lookforward_days,
        "filters": {"event_types": types_list, "region": region_filter},
    }


# === QUANT COMPUTATION ENDPOINTS ===

@app.get("/api/quant/correlation")
async def correlation_matrix(tickers: str, period: str = "3mo"):
    """Compute correlation matrix. tickers = comma-separated (e.g., AAPL,MSFT,GOOGL)."""
    from quant.computations import compute_correlation_matrix
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if len(ticker_list) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 tickers")
    return compute_correlation_matrix(ticker_list, period)


@app.get("/api/quant/drawdown/{ticker}")
async def drawdown(ticker: str, period: str = "6mo"):
    """Compute drawdown from peak for a ticker."""
    from quant.computations import compute_drawdown
    return compute_drawdown(ticker.upper(), period)


@app.get("/api/quant/volatility/{ticker}")
async def volatility(ticker: str, period: str = "6mo"):
    """Compute realized vol, Sharpe, VaR, skewness for a ticker."""
    from quant.computations import compute_volatility_metrics
    return compute_volatility_metrics(ticker.upper(), period)


@app.get("/api/quant/options/{ticker}")
async def options_analysis(ticker: str):
    """Computed options analytics: Greeks, IV, put/call ratio, unusual activity, implied move."""
    from quant.options_analytics import analyze_options
    return analyze_options(ticker.upper())


@app.get("/api/quant/enrich")
async def enrich_tickers(tickers: str, period: str = "3mo"):
    """Compute enrichment data for a set of tickers: vol, drawdown, options, correlation.
    This is what differentiates from ChatGPT — computed analytics, not prose."""
    from quant.computations import compute_correlation_matrix, compute_drawdown, compute_volatility_metrics
    from quant.options_analytics import analyze_options
    from agents.nlp.sentiment import score_articles
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        raise HTTPException(status_code=400, detail="No tickers provided")

    result: dict = {"tickers": ticker_list, "analytics": {}, "correlation": None}

    # Per-ticker analytics — run concurrently (cap at 6 to conserve API)
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _enrich_one(t: str) -> tuple[str, dict]:
        try:
            vol = compute_volatility_metrics(t, period)
            dd = compute_drawdown(t, period)
            prices = market_client.get_price_history(t, period="1mo")
            options = analyze_options(t)
            articles = news_client.get_ticker_news(t, page_size=10)
            sentiment = score_articles(articles)
            return t, {
                "volatility": vol,
                "drawdown": dd,
                "sparkline": [{"date": p["date"], "close": p["close"]} for p in prices[-20:]],
                "options": options if "error" not in options else None,
                "sentiment": sentiment.get("aggregate"),
            }
        except Exception as e:
            logger.warning(f"Enrichment failed for {t}: {e}")
            return t, {"error": str(e)}

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_enrich_one, t) for t in ticker_list[:6]]
        for future in as_completed(futures):
            ticker_name, data = future.result()
            result["analytics"][ticker_name] = data

    # Correlation matrix (only if 2+ tickers)
    if len(ticker_list) >= 2:
        try:
            result["correlation"] = compute_correlation_matrix(ticker_list[:6], period)
        except Exception as e:
            logger.warning(f"Correlation computation failed: {e}")

    return result

# market_client singleton is defined above with other data clients


@app.get("/api/quant/macro-series")
async def macro_time_series():
    """Get macro time series for chart rendering."""
    from quant.computations import get_macro_time_series
    return get_macro_time_series()


# === RISK MANAGEMENT ===

@app.get("/api/quant/portfolio-risk")
async def portfolio_risk_analysis(req: Request):
    """Full portfolio risk dashboard: VaR, CVaR, sector exposure, circuit breaker.

    Scoped to the authenticated user's open trades only.
    """
    try:
        from quant.risk import compute_ewma_covariance, compute_portfolio_var, compute_portfolio_cvar, check_sector_limits, drawdown_circuit_breaker
        from quant.computations import compute_drawdown
    except Exception as e:
        logger.error(f"Import error in portfolio-risk: {e}")
        return {"error": str(e), "var_95": None, "cvar_95": None}

    user_id = require_user_id(req)

    # Get open trades for this user only
    try:
        from db.models import TradeRecord
        async with async_session() as session:
            result = await session.execute(
                select(TradeRecord).where(
                    TradeRecord.status == "open",
                    TradeRecord.user_id == user_id,
                )
            )
            trades = [
                {c.name: getattr(r, c.name) for c in r.__table__.columns}
                for r in result.scalars().all()
            ]
    except Exception as e:
        logger.error(f"Failed to get trades for risk: {e}")
        trades = []
    if not trades:
        return {"error": "No open positions", "var_95": None, "cvar_95": None}

    tickers = [t["ticker"] for t in trades]
    weights = {t["ticker"]: t.get("position_size_pct", 5) / 100 for t in trades}

    # Fetch returns
    returns_dict = {}
    sectors = {}
    for ticker in tickers:
        try:
            history = market_client.get_price_history(ticker, period="3mo")
            if history and len(history) > 20:
                closes = [b["close"] for b in history]
                rets = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
                returns_dict[ticker] = rets
            fundamentals = market_client.get_fundamentals(ticker)
            sectors[ticker] = {"sector": fundamentals.get("sector", "Unknown"), "weight": weights.get(ticker, 0)}
        except Exception as e:
            logger.warning(f"Portfolio risk: failed to fetch data for {ticker}: {e}")

    if len(returns_dict) < 1:
        return {"error": "Could not fetch price data"}

    # Portfolio returns series (used for CVaR + VaR bootstrap CI)
    port_returns = []
    min_len = min(len(r) for r in returns_dict.values()) if returns_dict else 0
    for i in range(min_len):
        daily = sum(weights.get(t, 0) * returns_dict[t][i] for t in returns_dict)
        port_returns.append(daily)

    # Compute (covariance with Ledoit-Wolf shrinkage; VaR with bootstrap CI + Cornish-Fisher)
    # Dollar VaR/CVaR anchored on the user's actual book size — see
    # infra/user_context.resolve_portfolio_base. A $10M Macro PM should
    # never see VaR rendered against a $100k retail base.
    portfolio_base = await resolve_portfolio_base(user_id)
    cov = compute_ewma_covariance(returns_dict)
    var_result = compute_portfolio_var(
        weights, cov, portfolio_value=portfolio_base, portfolio_returns=port_returns,
    )
    cvar_result = compute_portfolio_cvar(port_returns)

    # Sector check (uses GICS fallback for tickers Yahoo returns "Unknown" for)
    from data.sector_map import resolve_sector as _resolve_sector
    for tk, info in sectors.items():
        resolved, _ = _resolve_sector(tk, info.get("sector"))
        info["sector"] = resolved
    sector_result = check_sector_limits(sectors)

    # Drawdown — real book (open + closed P&L), not SPY proxy
    from agents.desk3_position_risk import get_current_portfolio_drawdown
    real_dd = await get_current_portfolio_drawdown(async_session, user_id=user_id)
    circuit = drawdown_circuit_breaker(real_dd)

    return {
        **var_result,
        **cvar_result,
        "sector_exposure": sector_result,
        "circuit_breaker": circuit,
        "correlation_matrix": cov,
        "positions_count": len(tickers),
        "portfolio_drawdown_pct": round(float(real_dd), 2),
        "portfolio_base": portfolio_base,
    }


@app.get("/api/quant/stress")
async def stress_panel(req: Request):
    """
    Run the full stress panel on the authenticated user's open book.

    Returns historical scenarios (GFC 2008, COVID 2020, rate shock 2022,
    dot-com 2000) and parametric hypothetical shocks (VIX +15/+30, credit
    +200/+500bp, oil +50/-30%, plus a combined risk-off cocktail).
    """
    from db.models import TradeRecord
    from quant.stress import run_full_stress_panel
    from data.sector_map import resolve_sector

    user_id = require_user_id(req)

    try:
        async with async_session() as session:
            result = await session.execute(
                select(TradeRecord).where(
                    TradeRecord.status == "open",
                    TradeRecord.user_id == user_id,
                )
            )
            trades = result.scalars().all()
    except Exception as e:
        logger.error(f"stress_panel: failed to load trades: {e}")
        return {"error": str(e), "historical": {}, "hypothetical": []}

    if not trades:
        return {"error": "No open positions", "historical": {}, "hypothetical": []}

    # Resolve sectors for each position via GICS fallback so stress math
    # never falls into "Unknown" silently.
    positions = []
    for t in trades:
        yahoo_sector = None
        try:
            fund = market_client.get_fundamentals(t.ticker)
            yahoo_sector = (fund or {}).get("sector")
        except Exception:
            pass
        sector, _ = resolve_sector(t.ticker, yahoo_sector)
        positions.append({
            "ticker": t.ticker,
            "sector": sector,
            "size_pct": float(t.position_size_pct or 0),
            "direction": t.direction or "bullish",
        })

    portfolio_base = await resolve_portfolio_base(user_id)
    return run_full_stress_panel(positions, portfolio_base=portfolio_base)


@app.post("/api/quant/scenario/custom")
async def custom_scenario(payload: dict, req: Request):
    """
    Run a custom cross-asset stress scenario on the authenticated user's
    open book (or an ad-hoc position set). Per-position betas to rates /
    credit / commodities / FX are fit at request time from 1y daily
    history — no hardcoded sector tables on this path.

    Body:
        {
            "shock": {
                "rates_shock_bps":   <int|float, default 0>,
                "credit_shock_bps":  <int|float, default 0>,
                "oil_shock_pct":     <float, default 0>,
                "gold_shock_pct":    <float, default 0>,
                "fx_shock_pct":      <float, default 0>
            },
            "positions": [ ... ]  (optional; defaults to user's open book)
        }
    """
    from db.models import TradeRecord
    from quant.stress import custom_macro_scenario

    user_id = require_user_id(req)
    shock = payload.get("shock") or {}
    positions = payload.get("positions") or []

    if not positions:
        try:
            async with async_session() as session:
                result = await session.execute(
                    select(TradeRecord).where(
                        TradeRecord.status == "open",
                        TradeRecord.user_id == user_id,
                    )
                )
                trades = result.scalars().all()
        except Exception as e:
            logger.error(f"custom_scenario: failed to load trades: {e}")
            raise HTTPException(status_code=500, detail=str(e))
        if not trades:
            raise HTTPException(status_code=400, detail="No open positions and no positions passed in body")
        positions = [
            {
                "ticker": t.ticker,
                "size_pct": float(t.position_size_pct or 0),
                "direction": t.direction or "bullish",
            }
            for t in trades
        ]

    portfolio_base = await resolve_portfolio_base(user_id)
    return custom_macro_scenario(positions, shock, portfolio_base=portfolio_base)


@app.get("/api/quant/cross-asset-correlation")
async def cross_asset_correlation(tickers: str = "", include_macro: bool = True, period: str = "6mo"):
    """
    Cross-asset correlation matrix: user-supplied equity tickers PLUS the
    rates / credit / commodities / FX / vol ETF proxies. The macro PM's
    view of how their book correlates with the rest of the tape.
    """
    from quant.computations import compute_cross_asset_correlation

    eq_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not eq_list:
        # Default to a small representative set
        eq_list = ["SPY", "QQQ"]
    return compute_cross_asset_correlation(
        eq_list, include_macro=include_macro, period=period,
    )


# Helper for internal use
async def list_trades_internal(status: str = "open") -> list[dict]:
    from db.models import TradeRecord
    async with async_session() as session:
        query = select(TradeRecord).order_by(desc(TradeRecord.opened_at))
        if status != "all":
            query = query.where(TradeRecord.status == status)
        result = await session.execute(query.limit(50))
        return [
            {c.name: getattr(r, c.name) for c in r.__table__.columns}
            for r in result.scalars().all()
        ]


def _current_regime_for_gate() -> tuple[str | None, float | None]:
    """
    Best-effort fetch of current macro regime so the trade gate can apply
    a regime-based size multiplier. Never raises — falls back to (None, None)
    so the gate just skips the multiplier instead of crashing.

    Only uses the cached snapshot — never triggers a live refresh, because
    this is hot-path on every trade-write. A stale (or missing) snapshot
    just falls back to no regime multiplier; trades never wait on FRED.
    """
    try:
        from quant.regime import classify_regime
        snapshot = fred_client._snapshot_cache or {}
        if not snapshot:
            return None, None
        vix = snapshot.get("vix", {}).get("value", 20)
        credit = snapshot.get("credit_spreads", {}).get("value", 3)
        yc = snapshot.get("yield_curve_spread", {}).get("value", 0.5)
        regime_data = classify_regime(vix, credit, yc)
        return regime_data.get("current_regime"), regime_data.get("confidence")
    except Exception as e:
        logger.debug(f"regime fetch failed (non-fatal): {e}")
        return None, None


# === REGIME DETECTION ===

@app.get("/api/quant/regime")
async def regime_detection():
    """Current macro regime from HMM + rule-based fallback.

    All FRED calls go through the async wrappers (run_sync) so we never
    block the event loop. The three series history fetches run concurrently
    rather than sequentially.
    """
    from quant.regime import classify_regime, fit_regime_model
    snapshot = await fred_client.aget_macro_snapshot()

    vix = snapshot.get("vix", {}).get("value", 20)
    credit = snapshot.get("credit_spreads", {}).get("value", 3)
    yc = snapshot.get("yield_curve_spread", {}).get("value", 0.5)

    # Try to fit model from FRED history — concurrent fetches with a hard
    # wall budget. If any series fails, we just skip model fitting and fall
    # back to the rule-based classifier.
    macro_hist: list[dict] = []
    try:
        results = await asyncio.wait_for(
            asyncio.gather(
                fred_client.aget_series_history("VIXCLS", 500),
                fred_client.aget_series_history("BAMLH0A0HYM2", 500),
                fred_client.aget_series_history("T10Y2Y", 500),
                return_exceptions=True,
            ),
            timeout=10.0,
        )
        vix_hist, credit_hist, yc_hist = [
            r if isinstance(r, list) else [] for r in results
        ]

        if vix_hist and credit_hist and yc_hist:
            min_len = min(len(vix_hist), len(credit_hist), len(yc_hist))
            macro_hist = [
                {"date": vix_hist[i]["date"], "vix": vix_hist[i]["value"],
                 "credit_spread": credit_hist[i]["value"], "yield_curve": yc_hist[i]["value"]}
                for i in range(min_len)
            ]
            await asyncio.get_running_loop().run_in_executor(None, fit_regime_model, macro_hist)
    except asyncio.TimeoutError:
        logger.warning("Regime: FRED history fetch exceeded 10s — using rule-based only")
    except Exception as e:
        logger.warning(f"Regime model fitting failed (using rule-based): {e}")

    # Pass the macro history as a window so classify_regime runs the
    # proper Bayesian forward filter over recent observations instead of
    # a single-point prediction. The transition matrix anchors today's
    # posterior to yesterday's belief — fixes the "single observation
    # produces extreme posterior" failure mode.
    return classify_regime(
        vix, credit, yc,
        macro_window=macro_hist if macro_hist else None,
    )


@app.get("/api/quant/regime/diagnostics")
async def regime_diagnostics():
    """HMM fit diagnostics for the operations UI.

    Surfaces converged flag, EM iterations, log-likelihood, cached
    label mapping, time since fit / TTL, hysteresis state. Useful for
    debugging regime calls in production — if the model didn't converge
    or the cache is stale, this endpoint says so.
    """
    from quant.regime import get_fit_diagnostics
    return get_fit_diagnostics()


# === BACKTESTING ===

@app.post("/api/backtest/run")
async def run_backtest(request: dict, req: Request):
    """Run a rules-based backtest."""
    from quant.backtester import run_rules_based_backtest, BacktestConfig
    from db.repositories import BacktestRepository

    user_id = require_user_id(req)
    tickers = request.get("tickers", ["AAPL", "MSFT", "GOOGL"])
    period = request.get("period", "1y")
    # Default backtest capital to the user's actual book size so the
    # equity curve is denominated in the right units. Override allowed
    # via request body for "what-if" scenarios at other sizes.
    initial_capital = request.get("initial_capital") or await resolve_portfolio_base(user_id)

    # Save run scoped to authenticated user
    run_id = await BacktestRepository.save_run({
        "user_id": user_id,
        "name": f"Backtest: {', '.join(tickers[:3])}",
        "tickers": tickers,
        "initial_capital": initial_capital,
        "mode": "rules_based",
        "status": "running",
    })

    try:
        config = BacktestConfig(initial_capital=initial_capital)
        results = run_rules_based_backtest(tickers, period=period, config=config)

        if "error" in results:
            await BacktestRepository.update_run_status(run_id, "failed", results["error"])
            return {"run_id": run_id, "error": results["error"]}

        # Save results
        await BacktestRepository.save_results({
            "backtest_run_id": run_id,
            "equity_curve": results.get("equity_curve", []),
            "drawdown_series": results.get("drawdown_series", []),
            "sharpe_ratio": results.get("sharpe_ratio"),
            "sortino_ratio": results.get("sortino_ratio"),
            "max_drawdown_pct": results.get("max_drawdown_pct"),
            "total_return_pct": results.get("total_return_pct"),
            "annualized_return_pct": results.get("annualized_return_pct"),
            "win_rate": results.get("win_rate"),
            "profit_factor": results.get("profit_factor"),
            "total_trades": results.get("total_trades"),
            "trades": results.get("trades", []),
            "benchmark_return_pct": results.get("benchmark_return_pct"),
            "benchmark_sharpe": results.get("benchmark_sharpe"),
        })

        await BacktestRepository.update_run_status(run_id, "completed")
        return {"run_id": run_id, "status": "completed", "results": results}
    except Exception as e:
        await BacktestRepository.update_run_status(run_id, "failed", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/backtest/runs")
async def list_backtest_runs(req: Request):
    """List backtest runs owned by the authenticated user."""
    from db.models import BacktestRunRecord
    user_id = require_user_id(req)
    async with async_session() as session:
        result = await session.execute(
            select(BacktestRunRecord)
            .where(BacktestRunRecord.user_id == user_id)
            .order_by(desc(BacktestRunRecord.created_at))
            .limit(50)
        )
        runs = [
            {c.name: getattr(r, c.name) for c in r.__table__.columns}
            for r in result.scalars().all()
        ]
    return {"runs": runs}


@app.get("/api/backtest/results/{run_id}")
async def get_backtest_results(run_id: str, req: Request):
    """Get results for a specific backtest run — owner-only."""
    from db.models import BacktestRunRecord, BacktestResultRecord
    user_id = require_user_id(req)
    async with async_session() as session:
        # Verify the requested run belongs to this user before exposing results.
        # BacktestResultRecord has no user_id of its own; ownership flows through the run.
        run = await session.execute(
            select(BacktestRunRecord).where(
                BacktestRunRecord.id == run_id,
                BacktestRunRecord.user_id == user_id,
            )
        )
        if not run.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Backtest not found")

        result = await session.execute(
            select(BacktestResultRecord).where(BacktestResultRecord.backtest_run_id == run_id)
        )
        record = result.scalar_one_or_none()
        if not record:
            raise HTTPException(status_code=404, detail="Backtest results not available")
        return {c.name: getattr(record, c.name) for c in record.__table__.columns}


# === YIELD CURVE ===

@app.get("/api/quant/curve")
async def yield_curve(as_of: str | None = None):
    """
    Current (or as-of-date) US Treasury yield curve from FRED CMT series,
    interpolated to 11 standard tenors (1M-30Y) via natural cubic spline.

    Returns level / slope / butterfly summary metrics suitable for a macro
    PM's regime check.
    """
    from quant.curve import get_curve
    return get_curve(date=as_of)


@app.get("/api/quant/curve/regime")
async def yield_curve_regime(history_days: int = 120):
    """
    Classify the last `history_days` of yield-curve evolution into one of
    bull_steepener / bull_flattener / bear_steepener / bear_flattener / stable.
    """
    from quant.curve import curve_regime
    return curve_regime(history_days=history_days)


@app.post("/api/quant/curve/key-rate-durations")
async def yield_curve_krd(payload: dict):
    """
    Empirical key-rate sensitivities for a list of tickers via joint OLS
    regression of asset returns on Δyield at {2Y, 5Y, 10Y, 30Y}.

    Body: {
        "tickers": ["TLT", "IEF", "SPY", ...],
        "lookback_days": 252  (optional, default 252)
    }
    """
    from quant.curve import key_rate_durations
    tickers = [t.strip().upper() for t in (payload.get("tickers") or []) if t]
    if not tickers:
        raise HTTPException(status_code=400, detail="No tickers provided")
    lookback = int(payload.get("lookback_days", 252))
    history_dict: dict[str, list[dict]] = {}
    for t in tickers[:20]:  # cap to protect rate limits
        try:
            hist = market_client.get_price_history(t, period="1y" if lookback <= 365 else "2y")
            if hist:
                history_dict[t] = hist
        except Exception as e:
            logger.warning(f"KRD price fetch failed for {t}: {e}")
    if not history_dict:
        raise HTTPException(status_code=502, detail="No price history available for requested tickers")
    return key_rate_durations(history_dict, lookback_days=lookback)


# === FACTOR ANALYSIS ===

@app.get("/api/quant/factors")
async def factor_analysis(
    req: Request,
    tickers: str = "SPY",
    model: str = "single",
    benchmark: str | None = None,
):
    """
    Factor loadings and attribution for given tickers.

    `model` selects:
      "single"   — CAPM single-factor (market). Fast.
      "ff5_mom"  — FF5-style + Low-Vol + Momentum, computed from ETF proxies
                   (SPY, IWM, IWD/IWF, QUAL, USMV, MTUM). Slower (extra ETF
                   data fetches) but surfaces size/value/profitability/
                   low_vol/momentum exposure. USMV-based low_vol stands in
                   for the FF CMA "investment" factor (no public CMA proxy).
                   Returns alpha p-value with `alpha_significant_at_5pct`
                   plus VIF diagnostics and a `multicollinearity_flag`.
    """
    from quant.factors import (
        compute_factor_loadings,
        compute_multi_factor_loadings,
        compute_rolling_factor_exposure,
        build_proxy_factor_returns,
        attribute_alpha_vs_factor,
    )
    ticker_list = [t.strip().upper() for t in tickers.split(",")]

    # Get per-ticker return series
    ticker_returns: dict[str, list[float]] = {}
    for t in ticker_list[:5]:
        try:
            history = market_client.get_price_history(t, period="6mo")
            if history and len(history) > 30:
                closes = [b["close"] for b in history]
                rets = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
                ticker_returns[t] = rets
        except Exception:
            logger.warning(f"Factor analysis: failed to fetch {t}")

    # Benchmark — honor the user's preference from /api/me/profile so
    # a QQQ-benchmarked PM doesn't see all their alpha quoted vs SPY.
    # Query-string override (`benchmark=...`) wins over profile.
    user_id = get_user_id(req)
    if benchmark:
        bench_ticker = benchmark.upper()
    else:
        user_ctx = await resolve_user_context(user_id)
        bench_ticker = user_ctx["benchmark"]

    try:
        bench_hist = market_client.get_price_history(bench_ticker, period="6mo")
        bench_closes = [b["close"] for b in bench_hist]
        benchmark = [(bench_closes[i] - bench_closes[i-1]) / bench_closes[i-1] for i in range(1, len(bench_closes))]
    except Exception as e:
        logger.warning(f"Factor analysis: failed to fetch {bench_ticker} benchmark: {e}")
        benchmark = []

    if not ticker_returns or not benchmark:
        return {"error": "Insufficient data for factor analysis"}

    # Equal-weighted portfolio aligned to shortest length
    min_len = min(len(r) for r in ticker_returns.values())
    min_len = min(min_len, len(benchmark))
    n_tickers = len(ticker_returns)
    port_returns = [
        sum(ticker_returns[t][i] for t in ticker_returns) / n_tickers
        for i in range(min_len)
    ]
    benchmark = benchmark[:min_len]

    # Single-factor (always computed, used for rolling viz)
    single = compute_factor_loadings(port_returns, benchmark)
    rolling = compute_rolling_factor_exposure(port_returns, benchmark, window=30)

    response: dict = {
        "tickers": ticker_list,
        "benchmark": bench_ticker,
        "model": "single",
        **single,
        "rolling_exposures": rolling,
    }

    if model == "ff5_mom":
        proxies = build_proxy_factor_returns(period="6mo")
        if proxies:
            # Align all factor series to portfolio length
            aligned = {k: v[-min_len:] for k, v in proxies.items() if len(v) >= min_len}
            if "market" in aligned and len(aligned) >= 2:
                multi = compute_multi_factor_loadings(port_returns, aligned)
                response["multi_factor"] = multi
                response["model"] = multi.get("model", "ff5_mom")
                # Alpha vs factor variance decomposition + idiosyncratic Sharpe.
                # Surfaces what the regression actually means in PM language.
                response["alpha_vs_factor"] = attribute_alpha_vs_factor(
                    port_returns, aligned,
                )
                # Per-ticker decomposition — PMs want to see which names are
                # idiosyncratic vs factor-driven, not just portfolio-level.
                per_ticker: dict = {}
                for tk, rets in ticker_returns.items():
                    if len(rets) >= min_len:
                        per_ticker[tk] = attribute_alpha_vs_factor(
                            rets[-min_len:], aligned,
                        )
                response["alpha_vs_factor_per_ticker"] = per_ticker
            else:
                response["multi_factor"] = {"error": "Could not align factor proxies"}
        else:
            response["multi_factor"] = {"error": "Factor proxy ETFs unavailable"}

    return response


@app.get("/api/quant/risk-check/{ticker}")
async def pre_trade_check(ticker: str, size_pct: float = 0.03, action: str = "BUY"):
    """Pre-trade risk gate: checks position size, sector, correlation, marginal VaR."""
    from quant.risk import pre_trade_risk_check

    ticker = ticker.upper()
    trades = await list_trades_internal("open")
    positions = {}
    returns_dict = {}

    for t in trades:
        tk = t["ticker"]
        positions[tk] = {"sector": "Unknown", "weight": (t.get("position_size_pct") or 5) / 100}
        try:
            history = market_client.get_price_history(tk, period="3mo")
            if history and len(history) > 20:
                closes = [b["close"] for b in history]
                returns_dict[tk] = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
            fundamentals = market_client.get_fundamentals(tk)
            positions[tk]["sector"] = fundamentals.get("sector", "Unknown")
        except Exception as e:
            logger.warning(f"Pre-trade check: failed to fetch data for {tk}: {e}")

    # Also fetch new ticker returns
    try:
        history = market_client.get_price_history(ticker, period="3mo")
        if history and len(history) > 20:
            closes = [b["close"] for b in history]
            returns_dict[ticker] = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
        fundamentals = market_client.get_fundamentals(ticker)
        positions.setdefault(ticker, {})["sector"] = fundamentals.get("sector", "Unknown")
    except Exception as e:
        logger.warning(f"Pre-trade check: failed to fetch data for {ticker}: {e}")

    return pre_trade_risk_check(ticker, action, size_pct / 100, positions, returns_dict)


@app.get("/api/quant/regime/conditional-returns")
async def regime_conditional(req: Request, ticker: str | None = None):
    """Historical average returns of an asset in each regime.

    Defaults `ticker` to the user's preferred benchmark when not specified
    so a QQQ-benchmarked PM sees QQQ regime returns by default, not SPY's.
    """
    from quant.regime import classify_regime, fit_regime_model, get_regime_history, regime_conditional_returns

    if not ticker:
        user_id = get_user_id(req)
        user_ctx = await resolve_user_context(user_id)
        ticker = user_ctx["benchmark"]

    # Get macro history for regime classification — concurrent + bounded.
    try:
        results = await asyncio.wait_for(
            asyncio.gather(
                fred_client.aget_series_history("VIXCLS", 500),
                fred_client.aget_series_history("BAMLH0A0HYM2", 500),
                fred_client.aget_series_history("T10Y2Y", 500),
                return_exceptions=True,
            ),
            timeout=10.0,
        )
        vix_hist, credit_hist, yc_hist = [
            r if isinstance(r, list) else [] for r in results
        ]
        if not (vix_hist and credit_hist and yc_hist):
            return {"error": "Could not compute regime history"}

        min_len = min(len(vix_hist), len(credit_hist), len(yc_hist))
        macro_hist = [
            {"date": vix_hist[i]["date"], "vix": vix_hist[i]["value"],
             "credit_spread": credit_hist[i]["value"], "yield_curve": yc_hist[i]["value"]}
            for i in range(min_len)
        ]
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, fit_regime_model, macro_hist)
        regime_hist = await loop.run_in_executor(None, get_regime_history, macro_hist)
    except asyncio.TimeoutError:
        logger.warning("Regime conditional: FRED history fetch exceeded 10s")
        return {"error": "Could not compute regime history"}
    except Exception as e:
        logger.warning(f"Regime conditional: failed to compute regime history: {e}")
        return {"error": "Could not compute regime history"}

    # Get asset returns
    try:
        history = market_client.get_price_history(ticker.upper(), period="2y")
        if not history or len(history) < 60:
            return {"error": "Insufficient price data"}
        closes = [b["close"] for b in history]
        returns = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
    except Exception as e:
        logger.warning(f"Regime conditional: failed to fetch price data for {ticker}: {e}")
        return {"error": "Could not fetch price data"}

    return regime_conditional_returns(regime_hist, returns)


# === PORTFOLIO OPTIMIZATION ===

@app.post("/api/portfolio/optimize")
async def optimize_portfolio(request: dict):
    """Run Black-Litterman or mean-variance optimization."""
    from quant.optimizer import black_litterman, mean_variance_optimize, signals_to_views
    from quant.risk import compute_ewma_covariance

    tickers = request.get("tickers", [])
    method = request.get("method", "black_litterman")
    trade_ideas = request.get("trade_ideas", [])

    if not tickers:
        return {"error": "No tickers provided"}

    # Get returns for covariance
    returns_dict = {}
    for t in tickers[:10]:
        try:
            history = market_client.get_price_history(t, period="3mo")
            if history and len(history) > 20:
                closes = [b["close"] for b in history]
                rets = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
                returns_dict[t] = rets
        except Exception as e:
            logger.warning(f"Portfolio optimize: failed to fetch {t}: {e}")

    cov = compute_ewma_covariance(returns_dict)

    if method == "black_litterman" and trade_ideas:
        views, confidences = signals_to_views(trade_ideas)
        result = black_litterman(tickers, cov, views, confidences)
    else:
        expected_returns = {t: 0.10 for t in tickers}  # Default 10% expected
        result = mean_variance_optimize(expected_returns, cov)

    return result


# === MORNING REPORT ===

@app.get("/api/morning-report")
async def morning_report(req: Request):
    """Get today's morning report for the current user. Generates on first access, caches for the day."""
    from db.models import MorningReportRecord
    from datetime import date

    user_id = require_user_id(req)
    today = date.today().isoformat()

    # Check if this user already generated it today
    async with async_session() as session:
        result = await session.execute(
            select(MorningReportRecord).where(
                MorningReportRecord.report_date == today,
                MorningReportRecord.user_id == user_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing.full_report or {"report_date": today, "status": "empty"}

    # Generate new morning report via research desk
    from agents.orchestrator import run_research_desk
    try:
        memo = await run_research_desk(
            "Generate a pre-market morning briefing for today. "
            "Assess the macro regime, identify overnight developments, key risk alerts, "
            "and surface 3-5 actionable trade opportunities across sectors.",
            user_id=user_id,
        )
        report_data = memo.model_dump(mode="json")
        report_data["report_date"] = today

        # Persist scoped to this user
        async with async_session() as session:
            record = MorningReportRecord(
                user_id=user_id,
                report_date=today,
                executive_briefing=memo.executive_summary,
                macro_regime=memo.macro_regime,
                key_macro_changes=memo.key_findings,
                risk_alerts=[rf.description if hasattr(rf, "description") else str(rf) for rf in memo.risk_factors[:3]],
                overnight_opportunities=[ti.model_dump() if hasattr(ti, "model_dump") else ti for ti in memo.trade_ideas],
                full_report=report_data,
            )
            session.add(record)
            await session.commit()

        return report_data
    except Exception as e:
        logger.error(f"Morning report generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# === AGENT ENDPOINTS ===

@app.get("/api/agents/status")
async def agent_status():
    """Health check for all research desk agents."""
    agents = {
        "query_interpreter": "idle",
        "research_analyst": "idle",
        "risk_manager": "idle",
        "portfolio_strategist": "idle",
        "cio_synthesizer": "idle",
    }
    return {"agents": agents}


# === TRADE JOURNAL & PORTFOLIO ===

class TakeTradeRequest(BaseModel):
    memo_id: str = ""
    ticker: str
    direction: str
    action: str = "BUY"
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    position_size_pct: float = 0
    conviction: int = 50
    thesis: str = ""
    md_notes: str = ""


class RiskCheckRequest(BaseModel):
    ticker: str
    direction: str
    size_pct: float


@app.post("/api/portfolio/risk-check")
async def pre_trade_gate(req: RiskCheckRequest, request: Request):
    """
    Pre-trade risk gate. Checks a proposed trade against enforced limits:
    position size, sector concentration, correlation, marginal VaR,
    drawdown circuit breaker.

    Returns {approved, adjusted_size_pct, reasons, circuit_breaker, action}.
    Does NOT persist — use this to preview before calling /api/portfolio/trade.
    """
    from agents.desk3_position_risk import evaluate_trade_gate, get_current_portfolio_drawdown
    from db.models import TradeRecord

    user_id = require_user_id(request)

    # Gather existing open positions for context
    try:
        async with async_session() as session:
            q = select(TradeRecord).where(
                TradeRecord.status == "open",
                TradeRecord.user_id == user_id,
            )
            result = await session.execute(q)
            open_trades = result.scalars().all()

        existing_positions = []
        for t in open_trades:
            existing_positions.append({
                "ticker": t.ticker,
                "direction": t.direction,
                "size_pct": float(t.position_size_pct or 0),
                "sector": None,  # Will be fetched inside evaluator
            })
    except Exception as e:
        logger.error(f"Risk check: failed to load positions: {e}")
        existing_positions = []

    # Current portfolio drawdown
    dd = await get_current_portfolio_drawdown(async_session, user_id=user_id)

    # Regime-aware sizing
    regime, regime_conf = _current_regime_for_gate()

    # Per-user limit overrides (falls back to platform defaults on lookup failure)
    limits = await _resolve_user_limits(user_id)

    # Resolve the user's actual book size so liquidity checks size in
    # real dollars, not the legacy $100k retail default.
    portfolio_base_usd = await resolve_portfolio_base(user_id)

    result = evaluate_trade_gate(
        ticker=req.ticker.upper(),
        direction=req.direction,
        proposed_size_pct=req.size_pct,
        existing_positions=existing_positions,
        portfolio_drawdown_pct=dd,
        regime=regime,
        regime_confidence=regime_conf,
        max_position_size=limits.get("max_position_pct"),
        max_sector_pct=limits.get("max_sector_pct"),
        marginal_var_block_pct=limits.get("marginal_var_block_pct"),
        silent_squeeze_threshold=limits.get("silent_squeeze_threshold"),
        min_position_size=limits.get("min_position_pct"),
        portfolio_base_usd=portfolio_base_usd,
    )
    return result


@app.post("/api/portfolio/trade")
async def take_trade(req: TakeTradeRequest, request: Request):
    """
    CIO takes a trade idea — runs risk gate first, persists if approved.

    The risk gate is MANDATORY and may:
    - BLOCK the trade (returns 422 with reasons)
    - REDUCE the size (persists at adjusted size with warning)
    - ALLOW as-is
    """
    from db.models import TradeRecord
    from agents.desk3_position_risk import evaluate_trade_gate, get_current_portfolio_drawdown

    user_id = require_user_id(request)

    # === RISK GATE (mandatory) ===
    if req.position_size_pct and req.position_size_pct > 0:
        try:
            async with async_session() as session:
                q = select(TradeRecord).where(
                    TradeRecord.status == "open",
                    TradeRecord.user_id == user_id,
                )
                result = await session.execute(q)
                open_trades = result.scalars().all()

            existing_positions = [
                {
                    "ticker": t.ticker,
                    "direction": t.direction,
                    "size_pct": float(t.position_size_pct or 0),
                    "sector": None,
                }
                for t in open_trades
            ]

            dd = await get_current_portfolio_drawdown(async_session, user_id=user_id)
            regime, regime_conf = _current_regime_for_gate()

            # Per-user limit overrides (falls back to platform defaults on lookup failure)
            limits = await _resolve_user_limits(user_id)

            # User-resolved book size for the liquidity ADV check
            portfolio_base_usd = await resolve_portfolio_base(user_id)

            gate = evaluate_trade_gate(
                ticker=req.ticker.upper(),
                direction=req.direction,
                proposed_size_pct=req.position_size_pct,
                existing_positions=existing_positions,
                portfolio_drawdown_pct=dd,
                regime=regime,
                regime_confidence=regime_conf,
                max_position_size=limits.get("max_position_pct"),
                max_sector_pct=limits.get("max_sector_pct"),
                marginal_var_block_pct=limits.get("marginal_var_block_pct"),
                silent_squeeze_threshold=limits.get("silent_squeeze_threshold"),
                min_position_size=limits.get("min_position_pct"),
                portfolio_base_usd=portfolio_base_usd,
            )

            if not gate.get("approved"):
                raise HTTPException(
                    status_code=422,
                    detail={
                        "blocked": True,
                        "reasons": gate.get("reasons", []),
                        "circuit_breaker": gate.get("circuit_breaker", {}),
                        "ticker": req.ticker,
                    },
                )

            # Apply adjusted size if gate modified it
            final_size_pct = gate.get("adjusted_size_pct", req.position_size_pct)
            size_adjusted = abs(final_size_pct - req.position_size_pct) > 0.01
        except HTTPException:
            raise
        except Exception as e:
            # Fail closed: a broken risk gate cannot be a free pass. Refuse the
            # trade with 503 and surface the error so the user knows why.
            logger.error(f"Risk gate raised unexpected error for {req.ticker}: {e}", exc_info=True)
            raise HTTPException(
                status_code=503,
                detail={
                    "blocked": True,
                    "reasons": [
                        "Risk gate failed to evaluate this trade — refusing rather than skipping the check.",
                        f"Error: {str(e)[:200]}",
                    ],
                    "ticker": req.ticker,
                },
            )
    else:
        # Zero-size or missing size: still let it through (the gate has nothing
        # to check), but mark gate as not-run so downstream knows.
        final_size_pct = req.position_size_pct
        size_adjusted = False
        gate = {"approved": True, "skipped": True, "reason": "no position size specified"}

    # If no entry_price provided, mark at current market — turns "Take Trade"
    # into a one-click paper-trading entry without requiring users to look up a price.
    entry_price = req.entry_price
    entry_filled_at_market = False
    if entry_price is None or entry_price <= 0:
        try:
            fundamentals = market_client.get_fundamentals(req.ticker.upper())
            current = fundamentals.get("current_price") if fundamentals else None
            if current and current > 0:
                entry_price = float(current)
                entry_filled_at_market = True
        except Exception as e:
            logger.warning(f"Could not fetch market entry for {req.ticker}: {e}")

    async with async_session() as session:
        record = TradeRecord(
            user_id=user_id,
            memo_id=req.memo_id,
            ticker=req.ticker,
            direction=req.direction,
            action=req.action,
            entry_price=entry_price,
            stop_loss=req.stop_loss,
            take_profit=req.take_profit,
            position_size_pct=final_size_pct,
            conviction=req.conviction,
            thesis=req.thesis,
            md_notes=req.md_notes,
            status="open",
        )
        session.add(record)
        await session.commit()
        response = {
            "id": record.id,
            "status": "open",
            "ticker": req.ticker,
            "size_pct": final_size_pct,
            "entry_price": entry_price,
            "entry_filled_at_market": entry_filled_at_market,
        }
        if size_adjusted:
            response["size_adjusted"] = True
            response["original_size_pct"] = req.position_size_pct
            response["adjusted_size_pct"] = final_size_pct
            response["adjustment_reasons"] = gate.get("reasons", [])
        # Surface liquidity assessment + regime + drawdown so the UI can show
        # the why behind any size adjustment, not just that it happened.
        if isinstance(gate, dict):
            if gate.get("liquidity"):
                response["liquidity"] = gate["liquidity"]
            if gate.get("regime_adjustment"):
                response["regime_adjustment"] = gate["regime_adjustment"]
            if gate.get("circuit_breaker"):
                response["circuit_breaker"] = gate["circuit_breaker"]
        return response


class CloseTradeRequest(BaseModel):
    exit_price: float
    notes: str = ""


@app.post("/api/portfolio/trade/{trade_id}/close")
async def close_trade(trade_id: str, req: CloseTradeRequest, request: Request):
    """Close an open trade with exit price. Computes realized P&L."""
    from db.models import TradeRecord
    from sqlalchemy import update as sql_update
    user_id = require_user_id(request)
    async with async_session() as session:
        result = await session.execute(
            select(TradeRecord).where(
                TradeRecord.id == trade_id,
                TradeRecord.user_id == user_id,
            )
        )
        trade = result.scalar_one_or_none()
        if not trade:
            raise HTTPException(status_code=404, detail="Trade not found")
        if trade.status != "open":
            raise HTTPException(status_code=400, detail="Trade already closed")

        # Compute P&L
        entry = trade.entry_price or 0
        is_long = "bullish" in (trade.direction or "")
        if is_long:
            pnl_pct = ((req.exit_price - entry) / entry * 100) if entry > 0 else 0
        else:
            pnl_pct = ((entry - req.exit_price) / entry * 100) if entry > 0 else 0

        await session.execute(
            sql_update(TradeRecord)
            .where(TradeRecord.id == trade_id)
            .values(
                status="closed",
                exit_price=req.exit_price,
                realized_pnl=round(pnl_pct, 2),
                closed_at=datetime.now(timezone.utc),
                md_notes=(trade.md_notes or "") + f"\nClosed: {req.notes}" if req.notes else trade.md_notes,
            )
        )
        await session.commit()
        return {"id": trade_id, "status": "closed", "realized_pnl_pct": round(pnl_pct, 2)}


class TradeStatusUpdate(BaseModel):
    working_status: str  # active | shelved | dismissed
    watchlist_id: str | None = None


@app.patch("/api/portfolio/trade/{trade_id}/status")
async def update_trade_status(trade_id: str, payload: TradeStatusUpdate, request: Request):
    """
    Update a trade's working-order status. Orthogonal to the open/closed
    lifecycle — a trade can be open AND shelved (PM is reconsidering).

    Allowed working_status values: active | shelved | dismissed.
    Optionally re-assigns the trade to a different watchlist.
    """
    from db.models import TradeRecord
    from sqlalchemy import update as sql_update

    allowed = {"active", "shelved", "dismissed"}
    if payload.working_status not in allowed:
        raise HTTPException(status_code=400, detail=f"working_status must be one of {sorted(allowed)}")

    user_id = require_user_id(request)
    async with async_session() as session:
        result = await session.execute(
            select(TradeRecord).where(
                TradeRecord.id == trade_id,
                TradeRecord.user_id == user_id,
            )
        )
        trade = result.scalar_one_or_none()
        if not trade:
            raise HTTPException(status_code=404, detail="Trade not found")

        updates = {"working_status": payload.working_status}
        if payload.watchlist_id is not None:
            # Empty string clears the assignment
            updates["watchlist_id"] = payload.watchlist_id or None

        await session.execute(
            sql_update(TradeRecord).where(TradeRecord.id == trade_id).values(**updates)
        )
        await session.commit()
        return {
            "id": trade_id,
            "working_status": payload.working_status,
            "watchlist_id": updates.get("watchlist_id"),
        }


@app.get("/api/memo/{memo_id}/thread")
async def get_memo_thread(memo_id: str, request: Request):
    """
    Return the full thread containing this memo, ordered by sequence.
    Used by the frontend to render the conversational chain.
    """
    from db.repositories import MemoRepository
    user_id = require_user_id(request)
    memo = await MemoRepository.get_by_id(memo_id)
    if not memo:
        raise HTTPException(status_code=404, detail="Memo not found")
    if memo.get("user_id") not in (None, user_id):
        raise HTTPException(status_code=403, detail="Cross-user access denied")
    thread_id = memo.get("thread_id") or memo.get("id")
    chain = await MemoRepository.get_thread(thread_id) if thread_id else [memo]
    # Filter cross-user just in case
    chain = [m for m in chain if m and m.get("user_id") in (None, user_id)]
    return {
        "thread_id": thread_id,
        "memos": chain,
        "n_memos": len(chain),
    }


@app.post("/api/portfolio/flush")
async def flush_positions(req: Request, scope: str = "open"):
    """
    Hard-delete this user's trades so they can take a fresh set of ideas.

    Scoped strictly to the authenticated user — cannot affect other users.
    `scope` can be "open" (default), "closed", or "all". Use sparingly.
    """
    from db.models import TradeRecord
    from sqlalchemy import delete as sql_delete

    user_id = require_user_id(req)
    if scope not in ("open", "closed", "all"):
        raise HTTPException(status_code=400, detail="scope must be open|closed|all")

    async with async_session() as session:
        stmt = sql_delete(TradeRecord).where(TradeRecord.user_id == user_id)
        if scope == "open":
            stmt = stmt.where(TradeRecord.status == "open")
        elif scope == "closed":
            stmt = stmt.where(TradeRecord.status != "open")
        result = await session.execute(stmt)
        await session.commit()
        deleted = result.rowcount or 0

    logger.info(f"flush_positions: user={user_id} scope={scope} deleted={deleted}")
    return {"deleted": deleted, "scope": scope}


@app.get("/api/portfolio/trades")
async def list_trades(req: Request, status: str = "all"):
    """Get trade journal for current user — open, closed, or all."""
    user_id = require_user_id(req)
    try:
        from db.models import TradeRecord
        async with async_session() as session:
            query = (
                select(TradeRecord)
                .where(TradeRecord.user_id == user_id)
                .order_by(desc(TradeRecord.opened_at))
            )
            if status != "all":
                query = query.where(TradeRecord.status == status)
            result = await session.execute(query.limit(50))
            records = result.scalars().all()
            return {
                "trades": [
                    {
                        "id": r.id,
                        "ticker": r.ticker,
                        "direction": r.direction,
                        "action": r.action,
                        "entry_price": r.entry_price,
                        "stop_loss": r.stop_loss,
                        "take_profit": r.take_profit,
                        "position_size_pct": r.position_size_pct,
                        "conviction": r.conviction,
                        "thesis": r.thesis,
                        "status": r.status,
                        "realized_pnl": r.realized_pnl,
                        "opened_at": r.opened_at.isoformat() if r.opened_at else None,
                        "closed_at": r.closed_at.isoformat() if r.closed_at else None,
                    }
                    for r in records
                ],
                "count": len(records),
            }
    except Exception as e:
        logger.error(f"Failed to list trades: {e}")
        return {"trades": [], "count": 0}


@app.get("/api/portfolio/backtest")
async def backtest_trades(req: Request):
    """Evaluate the authenticated user's open trades against current market prices."""
    from db.models import TradeRecord
    from quant.backtesting import evaluate_trades

    user_id = require_user_id(req)
    async with async_session() as session:
        result = await session.execute(
            select(TradeRecord).where(
                TradeRecord.status == "open",
                TradeRecord.user_id == user_id,
            )
        )
        records = result.scalars().all()
        trades = [
            {
                "id": r.id,
                "ticker": r.ticker,
                "direction": r.direction,
                "entry_price": r.entry_price,
                "stop_loss": r.stop_loss,
                "take_profit": r.take_profit,
                "conviction": r.conviction,
                "thesis": r.thesis,
                "opened_at": r.opened_at.isoformat() if r.opened_at else None,
            }
            for r in records
        ]

    evaluated = evaluate_trades(trades)

    # Summary stats
    wins = sum(1 for t in evaluated if t.get("evaluation", {}).get("hit_target"))
    losses = sum(1 for t in evaluated if t.get("evaluation", {}).get("hit_stop"))
    open_count = len(evaluated) - wins - losses

    return {
        "trades": evaluated,
        "summary": {
            "total": len(evaluated),
            "wins": wins,
            "losses": losses,
            "open": open_count,
            "win_rate": round(wins / max(wins + losses, 1) * 100, 1),
        },
    }


@app.get("/api/portfolio/risk")
async def portfolio_risk():
    """Portfolio-level risk metrics — delegates to the full quant risk endpoint."""
    return await portfolio_risk_analysis()


# === PDF EXPORT ===

def _pdf_response(pdf_bytes: bytes, filename: str):
    """Return a streaming PDF download response."""
    from fastapi.responses import Response
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )


@app.get("/api/export/memo/{memo_id}")
async def export_memo(memo_id: str, req: Request):
    """Export a single intelligence memo as PDF."""
    from exports.pdf_renderer import render_memo

    user_id = require_user_id(req)
    async with async_session() as session:
        result = await session.execute(
            select(IntelligenceMemoRecord).where(
                IntelligenceMemoRecord.id == memo_id,
                IntelligenceMemoRecord.user_id == user_id,
            )
        )
        record = result.scalar_one_or_none()
        if not record:
            raise HTTPException(status_code=404, detail="Memo not found")

        memo_data = {
            "id": record.id,
            "query": record.query,
            "title": record.title,
            "executive_summary": record.executive_summary,
            "analysis": record.analysis,
            "key_findings": record.key_findings or [],
            "macro_regime": record.macro_regime,
            "overall_risk_level": record.overall_risk_level,
            "risk_factors": record.risk_factors or [],
            "trade_ideas": record.trade_ideas or [],
            "portfolio_positioning": record.portfolio_positioning,
            "hedging_recommendations": record.hedging_recommendations or [],
            "tickers_analyzed": record.tickers_analyzed or [],
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }

    pdf = render_memo(memo_data)
    filename = f"alpha-engine-memo-{memo_id[:8]}.pdf"
    return _pdf_response(pdf, filename)


@app.get("/api/export/portfolio")
async def export_portfolio(req: Request):
    """Export full portfolio report as PDF."""
    from exports.pdf_renderer import render_portfolio

    user_id = require_user_id(req)

    # Reuse the positions endpoint logic
    pos_result = await portfolio_positions(req)
    positions = pos_result.get("positions", [])
    summary = pos_result.get("summary", {})

    # Attribution (may error if no trades)
    try:
        attr_result = await portfolio_attribution(req)
    except Exception:
        attr_result = None

    # Scorecard summary
    try:
        from agents.scorer import get_scorecard_summary
        scorecard = await get_scorecard_summary(async_session, user_id=user_id)
    except Exception:
        scorecard = None

    pdf = render_portfolio(positions, summary, attr_result, scorecard)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    return _pdf_response(pdf, f"alpha-engine-portfolio-{ts}.pdf")


@app.get("/api/export/scorecard")
async def export_scorecard(req: Request):
    """Export signal scorecard as PDF."""
    from exports.pdf_renderer import render_scorecard
    from agents.scorer import get_scorecard_summary

    user_id = require_user_id(req)

    summary = await get_scorecard_summary(async_session, user_id=user_id)

    async with async_session() as session:
        result = await session.execute(
            select(SignalScoreRecord)
            .where(SignalScoreRecord.user_id == user_id)
            .order_by(desc(SignalScoreRecord.signal_date))
            .limit(50)
        )
        signals = result.scalars().all()

    signals_list = [
        {
            "ticker": s.ticker,
            "direction": s.direction,
            "conviction": s.conviction,
            "signal_date": s.signal_date.isoformat() if s.signal_date else None,
            "return_1d": s.return_1d,
            "return_5d": s.return_5d,
            "return_20d": s.return_20d,
            "hit_1d": s.hit_1d,
            "hit_5d": s.hit_5d,
            "hit_20d": s.hit_20d,
        }
        for s in signals
    ]

    pdf = render_scorecard(summary, signals_list)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    return _pdf_response(pdf, f"alpha-engine-scorecard-{ts}.pdf")


@app.get("/api/export/morning")
async def export_morning(req: Request):
    """Export today's morning briefing as PDF."""
    from exports.pdf_renderer import render_morning_briefing
    from db.models import MorningReportRecord
    from datetime import date

    user_id = require_user_id(req)
    today = date.today().isoformat()

    async with async_session() as session:
        result = await session.execute(
            select(MorningReportRecord).where(
                MorningReportRecord.report_date == today,
                MorningReportRecord.user_id == user_id,
            )
        )
        record = result.scalar_one_or_none()

    if not record or not record.full_report:
        raise HTTPException(status_code=404, detail="No morning report for today — generate one first")

    pdf = render_morning_briefing(record.full_report)
    return _pdf_response(pdf, f"alpha-engine-morning-{today}.pdf")


@app.get("/api/export/range")
async def export_range(req: Request, start: str, end: str):
    """
    Export a date-range archive bundle: all memos + trades + portfolio summary
    for the specified date range. Dates in YYYY-MM-DD format.
    """
    from exports.pdf_renderer import render_range_bundle
    from db.models import TradeRecord
    from datetime import datetime as _dt

    user_id = require_user_id(req)

    try:
        start_dt = _dt.fromisoformat(start)
        end_dt = _dt.fromisoformat(end)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid date format — use YYYY-MM-DD")

    async with async_session() as session:
        memo_q = select(IntelligenceMemoRecord).where(
            IntelligenceMemoRecord.user_id == user_id,
            IntelligenceMemoRecord.created_at >= start_dt,
            IntelligenceMemoRecord.created_at <= end_dt,
        ).order_by(desc(IntelligenceMemoRecord.created_at))
        memo_result = await session.execute(memo_q)
        memos = [
            {
                "id": m.id,
                "title": m.title,
                "query": m.query,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "decision": getattr(m, "decision", "WATCH"),
            }
            for m in memo_result.scalars().all()
        ]

        trade_q = select(TradeRecord).where(
            TradeRecord.user_id == user_id,
            TradeRecord.opened_at >= start_dt,
            TradeRecord.opened_at <= end_dt,
        ).order_by(desc(TradeRecord.opened_at))
        trade_result = await session.execute(trade_q)
        trades = [
            {
                "ticker": t.ticker,
                "action": t.action,
                "direction": t.direction,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "position_size_pct": t.position_size_pct,
                "realized_pnl": t.realized_pnl,
                "status": t.status,
                "opened_at": t.opened_at.isoformat() if t.opened_at else None,
            }
            for t in trade_result.scalars().all()
        ]

    # Current positions + summary
    try:
        pos_result = await portfolio_positions(req)
        positions = pos_result.get("positions", [])
        summary = pos_result.get("summary", {})
    except Exception:
        positions = []
        summary = {}

    # Scorecard
    try:
        from agents.scorer import get_scorecard_summary
        scorecard = await get_scorecard_summary(async_session, user_id=user_id)
    except Exception:
        scorecard = None

    pdf = render_range_bundle(start, end, memos, trades, positions, summary, scorecard)
    return _pdf_response(pdf, f"alpha-engine-archive-{start}-to-{end}.pdf")


@app.get("/api/portfolio/attribution")
async def portfolio_attribution(req: Request):
    """
    Desk 6B — Attribution Analyst.

    Decompose portfolio returns into factor returns (beta to SPY, momentum)
    vs alpha (stock picking skill).
    """
    from quant.factors import compute_factor_loadings
    from db.models import TradeRecord

    user_id = require_user_id(req)

    try:
        async with async_session() as session:
            q = select(TradeRecord).where(TradeRecord.user_id == user_id)
            result = await session.execute(q)
            trades = result.scalars().all()
    except Exception as e:
        logger.error(f"attribution DB failed: {e}")
        return {"error": str(e)}

    if not trades:
        return {"error": "No trades to analyze", "trade_count": 0}

    # Build per-ticker return series weighted by position size
    ticker_weights: dict[str, float] = {}
    for t in trades:
        size = float(t.position_size_pct or 0) / 100.0
        if size <= 0:
            continue
        ticker_weights[t.ticker] = ticker_weights.get(t.ticker, 0) + size

    if not ticker_weights:
        return {"error": "No sized positions", "trade_count": 0}

    # Normalize weights
    total_weight = sum(ticker_weights.values())
    if total_weight == 0:
        return {"error": "Zero total weight"}
    ticker_weights = {t: w / total_weight for t, w in ticker_weights.items()}

    # Fetch returns for each ticker + SPY benchmark
    tickers = list(ticker_weights.keys())[:10]  # Cap at 10 to conserve API
    returns_dict: dict[str, list[float]] = {}
    for t in tickers:
        try:
            history = market_client.get_price_history(t, period="3mo")
            if history and len(history) > 20:
                closes = [b["close"] for b in history]
                rets = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
                returns_dict[t] = rets
        except Exception as e:
            logger.warning(f"Failed to fetch {t} for attribution: {e}")

    try:
        spy_history = market_client.get_price_history("SPY", period="3mo")
        spy_closes = [b["close"] for b in spy_history]
        benchmark = [(spy_closes[i] - spy_closes[i - 1]) / spy_closes[i - 1] for i in range(1, len(spy_closes))]
    except Exception as e:
        logger.warning(f"Failed to fetch SPY benchmark: {e}")
        return {"error": "Could not fetch SPY benchmark"}

    if not returns_dict or not benchmark:
        return {"error": "Insufficient data"}

    # Build portfolio return series (weighted by position size)
    min_len = min(len(r) for r in returns_dict.values())
    min_len = min(min_len, len(benchmark))
    port_returns = []
    for i in range(min_len):
        daily = sum(
            ticker_weights.get(t, 0) * returns_dict[t][i]
            for t in returns_dict
        )
        port_returns.append(daily)
    benchmark = benchmark[:min_len]

    loadings = compute_factor_loadings(port_returns, benchmark)

    # Decompose: total return = alpha + beta*market_return + residual
    alpha = loadings.get("alpha", 0)
    beta = loadings.get("beta", 1)
    r_squared = loadings.get("r_squared", 0)
    residual_vol = loadings.get("residual_vol", 0)

    # Compute total return in observation window
    total_port_return = sum(port_returns) * 100  # %
    total_market_return = sum(benchmark) * 100
    factor_contribution = beta * total_market_return
    alpha_contribution = alpha if alpha is not None else 0
    residual_contribution = total_port_return - factor_contribution - alpha_contribution

    return {
        "trade_count": len(trades),
        "unique_tickers": len(ticker_weights),
        "period_return_pct": round(total_port_return, 2),
        "benchmark_return_pct": round(total_market_return, 2),
        "decomposition": {
            "alpha_pct": round(alpha_contribution, 2) if alpha_contribution is not None else None,
            "beta_contribution_pct": round(factor_contribution, 2),
            "residual_pct": round(residual_contribution, 2),
        },
        "factor_loadings": {
            "alpha": alpha,
            "beta": beta,
            "r_squared": r_squared,
            "residual_vol": residual_vol,
        },
        "weights": {t: round(w * 100, 2) for t, w in ticker_weights.items()},
    }


@app.post("/api/portfolio/snapshot/run")
async def run_eod_snapshot(req: Request):
    """Compute + persist the EOD snapshot for the authenticated user.

    Called by:
      - Frontend "Snapshot now" button on /portfolio
      - Railway cron (scheduled task) — same endpoint, auth via the
        platform's standard Clerk JWT scoped to a service account

    Idempotent on (user_id, today_NY). Rerunning the same day overwrites
    the existing rollup row and per-position rows.
    """
    user_id = require_user_id(req)
    from infra.eod_snapshot import compute_eod_snapshot
    result = await compute_eod_snapshot(user_id)
    return result


@app.post("/api/price-tape/refresh")
async def refresh_price_tape(req: Request):
    """Refresh the daily price tape (one grouped Massive call -> Postgres).

    Cron-callable (run once after market close). All pricing then reads the
    persisted tape instead of the rate-limited Massive API. Idempotent: a
    rerun for the same trading day is a no-op.
    """
    require_user_id(req)
    from data import price_tape
    n = await price_tape.refresh_tape(force=True)
    from db.repositories import PriceTapeRepository
    return {"rows_written": n, "tape_date": str(await PriceTapeRepository.latest_date())}


@app.get("/api/portfolio/equity-curve")
async def portfolio_equity_curve(req: Request, days: int = 90):
    """User-scoped equity curve time series for the portfolio chart.

    `days` caps the lookback (default 90). Each point: snapshot_date,
    total_value, daily_pnl_pct, cumulative_pnl_pct. Empty list when
    the user has no snapshots yet — frontend shows the empty-state.
    """
    user_id = require_user_id(req)
    from db.repositories import SnapshotRepository
    days = max(1, min(int(days or 90), 730))
    rows = await SnapshotRepository.get_equity_curve(user_id, days=days)
    series = [
        {
            "date": (r.get("snapshot_date").isoformat()
                     if hasattr(r.get("snapshot_date"), "isoformat")
                     else str(r.get("snapshot_date"))),
            "total_value": float(r.get("total_value") or 0),
            "daily_pnl": float(r.get("daily_pnl") or 0),
            "daily_pnl_pct": float(r.get("daily_pnl_pct") or 0),
            "cumulative_pnl": float(r.get("cumulative_pnl") or 0),
            "cumulative_pnl_pct": float(r.get("cumulative_pnl_pct") or 0),
        }
        for r in rows
    ]
    return {
        "series": series,
        "count": len(series),
        "latest": series[-1] if series else None,
    }


@app.get("/api/track-record/verify")
async def track_record_verify(req: Request):
    """Tamper-evidence check on the forward track record (Build Plan §3.3).

    Recomputes the hash chain over the user's scored signals and compares it
    to the latest stored anchor. ok=False means a historical scored signal
    was altered, reordered, or deleted.
    """
    user_id = require_user_id(req)
    from infra.track_record_store import verify_track_record
    return await verify_track_record(user_id)


@app.post("/api/track-record/anchor")
async def track_record_anchor(req: Request):
    """Commit the current track-record chain head as a new append-only anchor."""
    user_id = require_user_id(req)
    from infra.track_record_store import anchor_track_record
    return await anchor_track_record(user_id)


@app.get("/api/portfolio/positions")
async def portfolio_positions(req: Request):
    """
    Aggregated positions with live P&L.

    Groups open trades by ticker, fetches current prices concurrently,
    computes per-position unrealized P&L, weights, and portfolio summary.
    """
    user_id = require_user_id(req)
    from db.models import TradeRecord
    from concurrent.futures import ThreadPoolExecutor

    try:
        async with async_session() as session:
            # Open trades for user
            open_q = select(TradeRecord).where(
                TradeRecord.status == "open",
                TradeRecord.user_id == user_id,
            )
            open_result = await session.execute(open_q)
            open_trades = open_result.scalars().all()

            # Closed trades for realized P&L
            closed_q = select(TradeRecord).where(
                TradeRecord.status != "open",
                TradeRecord.user_id == user_id,
            )
            closed_result = await session.execute(closed_q)
            closed_trades = closed_result.scalars().all()
    except Exception as e:
        logger.error(f"portfolio_positions DB failed: {e}")
        return {"positions": [], "summary": {}, "error": str(e)}

    # Aggregate open trades by ticker
    grouped: dict[str, dict] = {}
    for t in open_trades:
        key = (t.ticker, t.direction)
        g = grouped.setdefault(key, {
            "ticker": t.ticker,
            "direction": t.direction,
            "total_size_pct": 0.0,
            "trades": [],
            "entry_prices": [],
            "weights": [],
            "stops": [],
            "targets": [],
            "earliest_opened": t.opened_at,
        })
        g["total_size_pct"] += float(t.position_size_pct or 0)
        g["trades"].append(t.id)
        if t.entry_price:
            g["entry_prices"].append(float(t.entry_price))
            g["weights"].append(float(t.position_size_pct or 0))
        if t.stop_loss:
            g["stops"].append(float(t.stop_loss))
        if t.take_profit:
            g["targets"].append(float(t.take_profit))
        if t.opened_at and (not g.get("earliest_opened") or t.opened_at < g["earliest_opened"]):
            g["earliest_opened"] = t.opened_at

    # Mark all positions from the persisted daily price tape (pure Postgres
    # read — no Massive call at request time). One grouped call/day populates
    # the tape; reads are free and survive rate limits, which is why the
    # portfolio now marks reliably.
    tickers = list({g["ticker"] for g in grouped.values()})
    prices: dict[str, float | None] = {}
    if tickers:
        try:
            from data import price_tape
            prices = dict(await price_tape.aget_tape_prices(tickers) or {})
        except Exception as e:
            logger.warning(f"Failed to price positions from tape: {e}")

    # Compute per-position metrics.
    # portfolio_base honors the user's onboarding/Settings value so the
    # "based on $X portfolio" label and every dollar figure in the panel
    # reflect their actual book, not the legacy $100k retail default.
    positions = []
    portfolio_base = await resolve_portfolio_base(user_id)
    total_unrealized = 0.0
    total_cost_basis = 0.0
    total_market_value = 0.0

    for g in grouped.values():
        # Weighted average entry price
        if g["weights"] and sum(g["weights"]) > 0:
            total_w = sum(g["weights"])
            avg_entry = sum(p * w for p, w in zip(g["entry_prices"], g["weights"])) / total_w
        elif g["entry_prices"]:
            avg_entry = sum(g["entry_prices"]) / len(g["entry_prices"])
        else:
            avg_entry = None

        current = prices.get(g["ticker"])
        is_long = "bullish" in (g["direction"] or "")
        is_short = "bearish" in (g["direction"] or "")

        pnl_pct = None
        pnl_dollars = None
        cost_basis = None
        market_value = None

        if avg_entry and current and avg_entry > 0:
            if is_long:
                pnl_pct = (current - avg_entry) / avg_entry * 100
            elif is_short:
                pnl_pct = (avg_entry - current) / avg_entry * 100

            # Dollar P&L based on position size
            size_fraction = g["total_size_pct"] / 100.0
            cost_basis = portfolio_base * size_fraction
            if pnl_pct is not None:
                pnl_dollars = cost_basis * (pnl_pct / 100.0)
                market_value = cost_basis + pnl_dollars
                total_unrealized += pnl_dollars
                total_cost_basis += cost_basis
                total_market_value += market_value

        avg_stop = sum(g["stops"]) / len(g["stops"]) if g["stops"] else None
        avg_target = sum(g["targets"]) / len(g["targets"]) if g["targets"] else None

        positions.append({
            "ticker": g["ticker"],
            "direction": g["direction"],
            "avg_entry_price": round(avg_entry, 2) if avg_entry else None,
            "current_price": round(current, 2) if current else None,
            "total_size_pct": round(g["total_size_pct"], 2),
            "unrealized_pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
            "unrealized_pnl_dollars": round(pnl_dollars, 2) if pnl_dollars is not None else None,
            "cost_basis": round(cost_basis, 2) if cost_basis else None,
            "market_value": round(market_value, 2) if market_value else None,
            "avg_stop_loss": round(avg_stop, 2) if avg_stop else None,
            "avg_take_profit": round(avg_target, 2) if avg_target else None,
            "trade_count": len(g["trades"]),
            "opened_at": g["earliest_opened"].isoformat() if g["earliest_opened"] else None,
            # Attached below from position_snapshots — populated only if
            # there are snapshot rows for any of this position's trade ids.
            "trade_ids": list(g["trades"]),
            "pnl_history": [],
        })

    # Attach 30-day pnl_history per position from position_snapshots.
    # One bulk read across all open-trade ids — no N+1. Multi-leg
    # positions (same ticker + direction across trades) are merged by
    # summing pnl_dollars per date.
    try:
        from db.repositories import SnapshotRepository
        all_trade_ids = [tid for p in positions for tid in p.get("trade_ids", [])]
        history_by_trade = await SnapshotRepository.get_position_history_bulk(
            user_id, all_trade_ids, days=30,
        )
        for p in positions:
            merged: dict[str, dict] = {}
            for tid in p.get("trade_ids", []):
                for row in history_by_trade.get(tid, []):
                    d_obj = row.get("snapshot_date")
                    d = d_obj.isoformat() if hasattr(d_obj, "isoformat") else str(d_obj)
                    bucket = merged.setdefault(d, {
                        "date": d,
                        "unrealized_pnl_pct": 0.0,
                        "unrealized_pnl_dollars": 0.0,
                        "market_value": 0.0,
                    })
                    bucket["unrealized_pnl_dollars"] += float(row.get("unrealized_pnl_dollars") or 0)
                    bucket["market_value"] += float(row.get("market_value") or 0)
                    # Weighted-by-cost pnl_pct: cost_basis × pct; we sum
                    # the numerator and divide at the end via market_value.
            # Replace the per-row pnl_pct with a cost-weighted recomputation
            # from the merged dollar totals so the sparkline tracks the
            # position-level number, not a single trade's.
            cost_basis_total = float(p.get("cost_basis") or 0)
            history = sorted(merged.values(), key=lambda x: x["date"])
            for h in history:
                if cost_basis_total > 0:
                    h["unrealized_pnl_pct"] = round(
                        h["unrealized_pnl_dollars"] / cost_basis_total * 100.0, 4
                    )
                else:
                    h["unrealized_pnl_pct"] = 0.0
                h["unrealized_pnl_dollars"] = round(h["unrealized_pnl_dollars"], 2)
                h["market_value"] = round(h["market_value"], 2)
            p["pnl_history"] = history
    except Exception as e:
        logger.warning(f"position pnl_history attach failed: {e}")

    # Sort by market value descending
    positions.sort(key=lambda p: p.get("market_value") or 0, reverse=True)

    # Realized P&L from closed trades
    realized_pnl_pct_sum = 0.0
    realized_trades_with_size = []
    wins = 0
    losses = 0
    for t in closed_trades:
        if t.realized_pnl is not None:
            realized_pnl_pct_sum += float(t.realized_pnl)
            realized_trades_with_size.append({
                "ticker": t.ticker,
                "pnl_pct": float(t.realized_pnl),
                "size_pct": float(t.position_size_pct or 0),
            })
            if t.realized_pnl > 0:
                wins += 1
            elif t.realized_pnl < 0:
                losses += 1

    # Realized dollars (weighted by position size)
    realized_dollars = sum(
        (r["pnl_pct"] / 100.0) * (portfolio_base * r["size_pct"] / 100.0)
        for r in realized_trades_with_size
    )

    total_closed = wins + losses
    win_rate = (wins / total_closed * 100) if total_closed > 0 else None

    # Compute weights (as % of total market value)
    if total_market_value > 0:
        for p in positions:
            if p.get("market_value"):
                p["weight_pct"] = round(p["market_value"] / total_market_value * 100, 2)
            else:
                p["weight_pct"] = None

    summary = {
        "portfolio_base": portfolio_base,
        "total_cost_basis": round(total_cost_basis, 2),
        "total_market_value": round(total_market_value, 2),
        "total_unrealized_pnl": round(total_unrealized, 2),
        "total_unrealized_pnl_pct": round(total_unrealized / total_cost_basis * 100, 2) if total_cost_basis > 0 else 0,
        "total_realized_pnl": round(realized_dollars, 2),
        "total_realized_pnl_pct_avg": round(realized_pnl_pct_sum / total_closed, 2) if total_closed > 0 else 0,
        "open_positions": len(positions),
        "closed_trades": total_closed,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 1) if win_rate is not None else None,
    }

    return {"positions": positions, "summary": summary}


# === SCORECARD (Desk 6) ===

@app.get("/api/scorecard/summary")
async def scorecard_summary(req: Request):
    """
    Aggregate signal quality metrics: hit rate, avg return, IC per conviction bucket.
    """
    from agents.scorer import get_scorecard_summary
    user_id = require_user_id(req)
    return await get_scorecard_summary(async_session, user_id=user_id)


@app.get("/api/scorecard/signals")
async def scorecard_signals(req: Request, limit: int = 50):
    """List individual signal scores with outcomes."""
    user_id = require_user_id(req)
    try:
        async with async_session() as session:
            q = (
                select(SignalScoreRecord)
                .where(SignalScoreRecord.user_id == user_id)
                .order_by(desc(SignalScoreRecord.signal_date))
                .limit(limit)
            )
            result = await session.execute(q)
            scores = result.scalars().all()
            return {
                "signals": [
                    {
                        "id": s.id,
                        "memo_id": s.memo_id,
                        "ticker": s.ticker,
                        "direction": s.direction,
                        "conviction": s.conviction,
                        "entry_price": s.entry_price,
                        "signal_date": s.signal_date.isoformat() if s.signal_date else None,
                        "price_1d": s.price_1d,
                        "price_5d": s.price_5d,
                        "price_20d": s.price_20d,
                        "return_1d": s.return_1d,
                        "return_5d": s.return_5d,
                        "return_20d": s.return_20d,
                        "hit_1d": s.hit_1d,
                        "hit_5d": s.hit_5d,
                        "hit_20d": s.hit_20d,
                    }
                    for s in scores
                ],
                "count": len(scores),
            }
    except Exception as e:
        logger.error(f"scorecard_signals failed: {e}")
        return {"signals": [], "count": 0}


@app.post("/api/scorecard/run")
async def scorecard_run(req: Request):
    """Manually trigger signal scoring job for the current user's memos."""
    from agents.scorer import score_pending_signals
    user_id = require_user_id(req)
    result = await score_pending_signals(async_session, user_id=user_id)
    return result


@app.get("/api/scorecard/rigor")
async def scorecard_rigor(req: Request, horizon: str = "5d"):
    """Phase 3 quant rigor over the live track record (Build Plan §3.1/§3.4).

    - Calibration: reliability curve + Brier score (conviction vs realized hit)
    - Deflated Sharpe over the realized per-signal returns (trial-count adjusted)
    - Tamper-evidence verdict from the hash chain
    Computed deterministically from signal_scores; never raises.
    """
    user_id = require_user_id(req)
    horizon = horizon if horizon in ("1d", "5d", "20d") else "5d"
    ret_key = f"return_{horizon}"
    hit_key = f"hit_{horizon}"
    rows: list[dict] = []
    try:
        async with async_session() as session:
            result = await session.execute(
                select(SignalScoreRecord)
                .where(SignalScoreRecord.user_id == user_id)
                .order_by(desc(SignalScoreRecord.signal_date))
                .limit(500)
            )
            for s in result.scalars().all():
                rows.append({
                    "conviction": s.conviction,
                    "hit_5d": s.hit_5d, "hit_1d": s.hit_1d, "hit_20d": s.hit_20d,
                    "return_5d": s.return_5d, "return_1d": s.return_1d, "return_20d": s.return_20d,
                })
    except Exception as e:
        logger.warning(f"scorecard_rigor fetch failed: {e}")

    out: dict = {"horizon": horizon, "n": len(rows)}
    try:
        from quant.conviction import calibration_report
        out["calibration"] = calibration_report(rows, horizon)
    except Exception as e:
        out["calibration"] = {"error": str(e)}
    try:
        from quant.overfitting import deflated_sharpe_ratio, bootstrap_sharpe_ci
        rets = [float(r[ret_key]) / 100.0 for r in rows if r.get(ret_key) is not None]
        if len(rets) >= 8:
            out["deflated_sharpe"] = deflated_sharpe_ratio(rets, n_trials=max(2, len(rets)))
            out["bootstrap_sharpe_ci"] = bootstrap_sharpe_ci(rets)
        else:
            out["deflated_sharpe"] = {"note": f"need >=8 scored signals, have {len(rets)}"}
    except Exception as e:
        out["deflated_sharpe"] = {"error": str(e)}
    try:
        from infra.track_record_store import verify_track_record
        out["tamper_evidence"] = await verify_track_record(user_id)
    except Exception as e:
        out["tamper_evidence"] = {"error": str(e)}
    return out


# === WATCHLIST ===

class AddWatchlistRequest(BaseModel):
    tickers: list[str]
    notes: str = ""


@app.get("/api/watchlist")
async def watchlist_list(req: Request):
    """List the user's watchlist tickers."""
    user_id = require_user_id(req)
    try:
        async with async_session() as session:
            q = (
                select(WatchlistRecord)
                .where(WatchlistRecord.user_id == user_id)
                .order_by(desc(WatchlistRecord.added_at))
            )
            result = await session.execute(q)
            items = result.scalars().all()
            return {
                "watchlist": [
                    {
                        "id": w.id,
                        "ticker": w.ticker,
                        "notes": w.notes or "",
                        "added_at": w.added_at.isoformat() if w.added_at else None,
                    }
                    for w in items
                ],
                "count": len(items),
            }
    except Exception as e:
        logger.error(f"watchlist_list failed: {e}")
        return {"watchlist": [], "count": 0}


@app.post("/api/watchlist")
async def watchlist_add(req: AddWatchlistRequest, request: Request):
    """Add one or more tickers to the user's watchlist."""
    user_id = require_user_id(request)
    tickers = [t.strip().upper() for t in req.tickers if t.strip()]
    if not tickers:
        raise HTTPException(status_code=400, detail="No tickers provided")

    added = []
    try:
        async with async_session() as session:
            for ticker in tickers:
                existing_q = select(WatchlistRecord).where(
                    WatchlistRecord.ticker == ticker,
                    WatchlistRecord.user_id == user_id,
                )
                existing = (await session.execute(existing_q)).scalar_one_or_none()
                if existing:
                    continue
                rec = WatchlistRecord(user_id=user_id, ticker=ticker, notes=req.notes)
                session.add(rec)
                added.append(ticker)
            await session.commit()
        return {"added": added, "count": len(added)}
    except Exception as e:
        logger.error(f"watchlist_add failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/watchlist/{ticker}")
async def watchlist_remove(ticker: str, req: Request):
    """Remove a ticker from the user's watchlist."""
    user_id = require_user_id(req)
    ticker = ticker.strip().upper()
    try:
        async with async_session() as session:
            q = select(WatchlistRecord).where(
                WatchlistRecord.ticker == ticker,
                WatchlistRecord.user_id == user_id,
            )
            result = await session.execute(q)
            rec = result.scalar_one_or_none()
            if not rec:
                raise HTTPException(status_code=404, detail="Ticker not in watchlist")
            await session.delete(rec)
            await session.commit()
        return {"removed": ticker}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"watchlist_remove failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# === STREAMING ANALYSIS ===

@app.post("/api/analyze/stream")
async def analyze_stream(request: AnalyzeRequest, req: Request):
    """SSE streaming endpoint — sends phase updates as agents complete."""
    from agents.orchestrator import (
        _query_interpreter, _research_analyst, _risk_manager,
        _portfolio_strategist, _cio_synthesizer, _with_timeout,
        IntelligenceMemo,
    )
    user_id = require_user_id(req)

    query = request.query.strip()

    # Tasks live at the outer scope so the wrapper generator below can cancel
    # them when the client disconnects. Without this, a disconnected browser
    # leaves the LLM pipeline running — burning Anthropic quota and leaking
    # worker memory.
    active_tasks: list[asyncio.Task] = []

    async def event_stream():
        def send(data: dict) -> str:
            try:
                return f"data: {json.dumps(data, default=str)}\n\n"
            except Exception:
                # Last resort — at least send something so the stream doesn't die
                safe = {k: str(v)[:200] if not isinstance(v, (str, int, float, bool, type(None))) else v for k, v in data.items()}
                return f"data: {json.dumps(safe, default=str)}\n\n"

        def keepalive() -> str:
            """SSE comment to keep the connection alive through proxies."""
            return ": keepalive\n\n"

        # Create a queue for live agent activity events
        from agents.stream_callbacks import DeskStreamCallback
        event_queue: asyncio.Queue = asyncio.Queue(maxsize=500)

        async def drain_queue():
            """Yield all queued events, non-blocking."""
            events = []
            while not event_queue.empty():
                try:
                    events.append(event_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            return events

        async def run_with_streaming(coro_factory, timeout_s: int, label: str):
            """
            Run an agent coroutine as a background task, yielding queue events
            as they arrive. Cancels the task on error or caller cancellation.
            """
            task = asyncio.create_task(
                asyncio.wait_for(coro_factory(), timeout=timeout_s)
            )
            active_tasks.append(task)
            events_to_yield: list = []
            last_keepalive = asyncio.get_event_loop().time()

            try:
                while not task.done():
                    try:
                        event = await asyncio.wait_for(event_queue.get(), timeout=1.5)
                        events_to_yield.append(event)
                    except asyncio.TimeoutError:
                        pass

                    now = asyncio.get_event_loop().time()
                    if now - last_keepalive > 10:
                        events_to_yield.append({"_keepalive": True})
                        last_keepalive = now

                    if events_to_yield:
                        yield events_to_yield
                        events_to_yield = []

                remaining = await drain_queue()
                if remaining:
                    yield remaining

                try:
                    result = await task
                    yield ("__result__", result)
                except asyncio.TimeoutError:
                    logger.error(f"[stream] {label} timed out after {timeout_s}s")
                    yield ("__result__", None)
                except asyncio.CancelledError:
                    # Propagate — outer cleanup will handle it.
                    raise
                except Exception as e:
                    logger.error(f"[stream] {label} raised: {e}")
                    yield ("__result__", None)
            except asyncio.CancelledError:
                # Client disconnected or pipeline aborted. Cancel the task and
                # re-raise so the outer generator's finally block runs.
                if not task.done():
                    task.cancel()
                raise
            finally:
                if task in active_tasks:
                    active_tasks.remove(task)

        # === Desk 1 (via current Query Interpreter): Intent parsing ===
        yield send({"type": "desk_start", "desk": "query", "label": "Query Interpretation", "agent": "query_interpreter"})
        yield send({"phase": "interpreting", "agent": "query_interpreter"})  # Backward compat
        qi_cb = DeskStreamCallback(event_queue, desk="query", agent="query_interpreter")

        # Pre-fetch macro context + scorecard so the Interpreter is regime-aware
        # and track-record-aware from the start of the pipeline.
        macro_context_for_interp: dict = {}
        scorecard_for_interp = None
        try:
            from agents.orchestrator import _fetch_macro_context, _fetch_scorecard_for_calibration
            macro_context_for_interp = await _fetch_macro_context()
            scorecard_for_interp = await _fetch_scorecard_for_calibration(user_id)
        except Exception as e:
            logger.debug(f"[stream] interpreter prefetch skipped: {e}")

        # Load thread context for follow-up queries.
        try:
            from agents.orchestrator import _load_thread_context
            thread_ctx = await _load_thread_context(request.parent_memo_id)
        except Exception as e:
            logger.warning(f"[stream] thread context load failed: {e}")
            thread_ctx = {}

        try:
            plan = await _with_timeout(
                _query_interpreter.interpret(
                    query,
                    callbacks=[qi_cb],
                    macro_context=macro_context_for_interp,
                    scorecard=scorecard_for_interp,
                    thread_context=thread_ctx,
                ),
                seconds=45, label="QI",
            )
            if not plan:
                yield send({"phase": "error", "error": "Query interpretation timed out"})
                return
            plan_data = plan.model_dump(mode="json")
            yield send({
                "type": "desk_done",
                "desk": "query",
                "summary": f"Intent: {plan_data.get('intent', '')} · {len(plan_data.get('tickers', []))} tickers",
                "tickers": plan_data.get("tickers", []),
                "intent": plan_data.get("intent", ""),
            })
            yield send({
                "phase": "interpreting_done",
                "tickers": plan_data.get("tickers", []),
                "intent": plan_data.get("intent", ""),
                "plan_confidence": plan_data.get("plan_confidence"),
                "plan_confidence_reason": plan_data.get("plan_confidence_reason"),
            })
        except Exception as e:
            logger.error(f"[stream] Query Interpreter failed: {e}")
            yield send({"phase": "error", "error": f"Query interpretation failed: {e}"})
            return

        # Accumulate each desk's tool calls so the provenance pipeline can
        # build the lineage + Fact Sheet for citations (mirrors the orchestrator).
        tool_steps_by_agent: dict = {}

        # === Desk 2: Research ===
        yield send({"type": "desk_start", "desk": "research", "label": "Research Desk", "agent": "research_analyst"})
        yield send({"phase": "researching", "agent": "research_analyst"})  # Backward compat
        research_cb = DeskStreamCallback(event_queue, desk="research", agent="research_analyst")
        research_start = asyncio.get_event_loop().time()
        try:
            async for chunk in run_with_streaming(
                lambda: _research_analyst.analyze({"plan": plan_data}, callbacks=[research_cb]),
                timeout_s=240, label="RA",
            ):
                if isinstance(chunk, tuple) and chunk[0] == "__result__":
                    output = chunk[1]
                    research_data = output.output if output and not output.error else {"data_summary": "Research unavailable."}
                    if output and getattr(output, "intermediate_steps", None):
                        tool_steps_by_agent["research_analyst"] = list(output.intermediate_steps)
                    # Run sub-question completeness heuristic
                    try:
                        from agents.orchestrator import _research_completeness_check
                        research_data = _research_completeness_check(plan_data, research_data)
                    except Exception as e:
                        logger.debug(f"[stream] completeness check skipped: {e}")
                else:
                    # chunk is a list of events
                    for evt in chunk:
                        if evt.get("_keepalive"):
                            yield keepalive()
                        else:
                            yield send(evt)
        except Exception as e:
            logger.error(f"[stream] Research Analyst failed: {e}")
            research_data = {"data_summary": f"Research failed: {e}"}

        research_duration = int((asyncio.get_event_loop().time() - research_start) * 1000)
        ticker_count = len(plan_data.get("tickers", []))
        yield send({
            "type": "desk_done",
            "desk": "research",
            "summary": f"{ticker_count} tickers researched",
            "duration_ms": research_duration,
        })
        yield send({"phase": "researching_done"})

        # === Desk 3: Risk ===
        yield send({"type": "desk_start", "desk": "risk", "label": "Risk Desk", "agent": "risk_manager"})
        yield send({"phase": "risk_assessment", "agent": "risk_manager"})  # Backward compat
        risk_cb = DeskStreamCallback(event_queue, desk="risk", agent="risk_manager")
        risk_start = asyncio.get_event_loop().time()
        try:
            async for chunk in run_with_streaming(
                lambda: _risk_manager.analyze({"plan": plan_data, "research": research_data}, callbacks=[risk_cb]),
                timeout_s=90, label="RM",
            ):
                if isinstance(chunk, tuple) and chunk[0] == "__result__":
                    output = chunk[1]
                    risk_data = output.output if output and not output.error else {
                        "macro_regime": "unknown", "regime_confidence": 0,
                        "risk_factors": [], "overall_risk_level": "elevated",
                        "risk_narrative": "Risk assessment unavailable.",
                    }
                    if output and getattr(output, "intermediate_steps", None):
                        tool_steps_by_agent["risk_manager"] = list(output.intermediate_steps)
                else:
                    for evt in chunk:
                        if evt.get("_keepalive"):
                            yield keepalive()
                        else:
                            yield send(evt)
        except Exception as e:
            logger.error(f"[stream] Risk Manager failed: {e}")
            risk_data = {
                "macro_regime": "unknown", "regime_confidence": 0,
                "risk_factors": [], "overall_risk_level": "elevated",
                "risk_narrative": f"Risk assessment failed: {e}",
            }

        risk_duration = int((asyncio.get_event_loop().time() - risk_start) * 1000)
        yield send({
            "type": "desk_done",
            "desk": "risk",
            "summary": f"Regime: {risk_data.get('macro_regime', '?')} · Level: {risk_data.get('overall_risk_level', '?')} · {len(risk_data.get('risk_factors', []))} risks",
            "duration_ms": risk_duration,
        })
        yield send({"phase": "risk_assessment_done", "macro_regime": risk_data.get("macro_regime", "")})

        # === Desk 4: Portfolio Construction ===
        yield send({"type": "desk_start", "desk": "portfolio", "label": "Portfolio Construction", "agent": "portfolio_strategist"})
        yield send({"phase": "strategizing", "agent": "portfolio_strategist"})  # Backward compat
        ps_cb = DeskStreamCallback(event_queue, desk="portfolio", agent="portfolio_strategist")
        ps_start = asyncio.get_event_loop().time()

        # Pull live portfolio so Strategist sizes ideas against the real book,
        # the scorecard for conviction calibration, and PRE-FETCH current
        # prices so the Strategist anchors entry/stop/target to live data
        # instead of inventing numbers from prose.
        portfolio_for_strategy = None
        scorecard_for_strategy = None
        live_prices_for_strategy: dict = {}
        try:
            from agents.orchestrator import (
                _fetch_portfolio_snapshot,
                _fetch_scorecard_for_calibration,
                _fetch_live_prices_for,
            )
            portfolio_for_strategy = await _fetch_portfolio_snapshot(user_id)
            scorecard_for_strategy = await _fetch_scorecard_for_calibration(user_id)
            # Pre-fetch prices for primary + top 8 secondary so the Strategist
            # has anchoring data for every candidate it might pick from.
            primary_tk = list(plan_data.get("tickers", []) or [])
            # Wide field of under-covered names (cached prices amortize the cost).
            _sec_cap = max(0, int(settings.STRATEGIST_PRICING_CAP) - len(primary_tk))
            secondary_tk = list((plan_data.get("secondary_universe", []) or [])[:_sec_cap])
            all_pricing = list(dict.fromkeys(primary_tk + secondary_tk))
            live_prices_for_strategy = await _fetch_live_prices_for(all_pricing)
        except Exception as e:
            logger.debug(f"[stream] Strategist prefetch skipped: {e}")

        try:
            async for chunk in run_with_streaming(
                lambda: _portfolio_strategist.analyze(
                    {
                        "plan": plan_data,
                        "research": research_data,
                        "risk": risk_data,
                        "portfolio": portfolio_for_strategy,
                        "scorecard": scorecard_for_strategy,
                        "live_prices": live_prices_for_strategy,
                        "macro_context": macro_context_for_interp,
                    }, callbacks=[ps_cb]
                ),
                timeout_s=90, label="PS",
            ):
                if isinstance(chunk, tuple) and chunk[0] == "__result__":
                    output = chunk[1]
                    strategy_data = output.output if output and not output.error else {
                        "trade_ideas": [], "portfolio_positioning": "neutral",
                        "hedging_recommendations": [], "strategy_narrative": "Strategy unavailable.",
                    }
                    if output and getattr(output, "intermediate_steps", None):
                        tool_steps_by_agent["portfolio_strategist"] = list(output.intermediate_steps)
                    # Post-validate trade ideas against live prices +
                    # diversity assessment (with required style labels).
                    if isinstance(strategy_data, dict):
                        try:
                            from agents.portfolio_strategist import (
                                validate_and_fix_trade_ideas, assess_diversity,
                            )
                            ideas = strategy_data.get("trade_ideas") or []
                            if live_prices_for_strategy:
                                ideas = validate_and_fix_trade_ideas(ideas, live_prices_for_strategy)
                                strategy_data["trade_ideas"] = ideas
                            strategy_data["_diversity"] = assess_diversity(
                                ideas,
                                required_style_labels=plan_data.get("required_style_labels", []),
                            )
                        except Exception as e:
                            logger.debug(f"[stream] trade-idea validator skipped: {e}")
                else:
                    for evt in chunk:
                        if evt.get("_keepalive"):
                            yield keepalive()
                        else:
                            yield send(evt)
        except Exception as e:
            logger.error(f"[stream] Portfolio Strategist failed: {e}")
            strategy_data = {
                "trade_ideas": [], "portfolio_positioning": "neutral",
                "hedging_recommendations": [], "strategy_narrative": f"Strategy failed: {e}",
            }

        ps_duration = int((asyncio.get_event_loop().time() - ps_start) * 1000)
        trade_count = len(strategy_data.get("trade_ideas", []))
        yield send({
            "type": "desk_done",
            "desk": "portfolio",
            "summary": f"{trade_count} trade ideas · {len(strategy_data.get('hedging_recommendations', []))} hedges",
            "duration_ms": ps_duration,
        })
        yield send({"phase": "strategizing_done", "trade_count": trade_count})

        # === Desk 5: CIO Synthesis ===
        yield send({"type": "desk_start", "desk": "cio", "label": "CIO Desk", "agent": "cio_synthesizer"})
        yield send({"phase": "synthesizing", "agent": "cio_synthesizer"})  # Backward compat
        cio_cb = DeskStreamCallback(event_queue, desk="cio", agent="cio_synthesizer")
        cio_start = asyncio.get_event_loop().time()

        # Adaptive calibration: reuse the scorecard fetched for Strategist so
        # CIO + Decision Gate see the same numbers and we don't double-fetch.
        scorecard_for_cio = scorecard_for_strategy

        # Continuity context: pull prior memos for ticker/theme overlap.
        prior_memos_for_cio: list[dict] = []
        try:
            from agents.orchestrator import _fetch_prior_memos
            prior_memos_for_cio = await _fetch_prior_memos(
                user_id,
                plan_data.get("tickers") or [],
                plan_data.get("themes") or [],
            )
        except Exception as e:
            logger.debug(f"[stream] Prior memos fetch skipped: {e}")

        try:
            output = await _with_timeout(
                _cio_synthesizer.synthesize(
                    {
                        "plan": plan_data,
                        "research": research_data,
                        "risk": risk_data,
                        "strategy": strategy_data,
                        "scorecard": scorecard_for_cio,
                        "prior_memos": prior_memos_for_cio,
                        "macro_context": macro_context_for_interp,
                    },
                    callbacks=[cio_cb],
                ),
                seconds=120, label="CIO",
            )
            memo_data = output.output if output and not output.error else None
        except Exception as e:
            logger.error(f"[stream] CIO Synthesizer failed: {e}")
            memo_data = None

        # Drain any remaining CIO events
        for evt in await drain_queue():
            yield send(evt)

        cio_duration = int((asyncio.get_event_loop().time() - cio_start) * 1000)

        # If CIO failed, build a useful memo from prior agent data instead of returning empty
        if not memo_data or not memo_data.get("title"):
            logger.warning("[stream] CIO failed — constructing memo from prior agent outputs")
            trade_ideas = strategy_data.get("trade_ideas", [])
            top_tickers = ", ".join(plan_data.get("tickers", [])[:4])
            memo_data = {
                "title": f"Analysis: {plan_data.get('query', 'Market Analysis')[:80]}",
                "executive_summary": (
                    f"Macro regime: {risk_data.get('macro_regime', 'unknown')}. "
                    f"Risk level: {risk_data.get('overall_risk_level', 'elevated')}. "
                    f"{len(trade_ideas)} trade ideas generated for {top_tickers}. "
                    f"{strategy_data.get('strategy_narrative', '')[:300]}"
                ),
                "analysis": research_data.get("data_summary", ""),
                "key_findings": [risk_data.get("risk_narrative", "")[:200]] if risk_data.get("risk_narrative") else [],
            }

        # CIO desk done
        yield send({
            "type": "desk_done",
            "desk": "cio",
            "summary": f"Memo: {memo_data.get('title', 'untitled')[:60]}",
            "duration_ms": cio_duration,
        })
        yield keepalive()

        # === Desk 5B: Decision Gate (programmatic — not LLM) ===
        from agents.desk5_decision_gate import compute_decision
        try:
            decision = compute_decision(
                trade_ideas=strategy_data.get("trade_ideas", []),
                macro_regime=risk_data.get("macro_regime", "unknown"),
                overall_risk_level=risk_data.get("overall_risk_level", "elevated"),
                scorecard=scorecard_for_cio,  # track-record-aware confidence
            )
            # Stream as a trace event (decision activity on CIO desk)
            yield send({
                "type": "decision",
                "desk": "cio",
                "agent": "decision_gate",
                "decision": decision.get("decision"),
                "reason": decision.get("reason"),
                "confidence": decision.get("confidence"),
                "timestamp": asyncio.get_event_loop().time(),
            })
        except Exception as e:
            logger.warning(f"Decision gate failed: {e}")
            decision = {"decision": "WATCH", "reason": f"Gate evaluation failed: {e}", "confidence": 0}

        # Inject structured data from prior agents (never trust LLM reconstruction)
        memo_data["query"] = query
        memo_data["intent"] = plan_data.get("intent", "thematic_research")
        memo_data["tickers_analyzed"] = plan_data.get("tickers", [])
        memo_data["themes"] = plan_data.get("themes", [])
        memo_data["macro_regime"] = risk_data.get("macro_regime", "")
        memo_data["overall_risk_level"] = risk_data.get("overall_risk_level", "")
        memo_data["risk_factors"] = risk_data.get("risk_factors", [])
        memo_data["trade_ideas"] = strategy_data.get("trade_ideas", [])
        memo_data["portfolio_positioning"] = strategy_data.get("portfolio_positioning", "")
        memo_data["hedging_recommendations"] = strategy_data.get("hedging_recommendations", [])
        # Decision gate output
        memo_data["decision"] = decision.get("decision", "WATCH")
        memo_data["decision_reason"] = decision.get("reason", "")
        memo_data["decision_confidence"] = decision.get("confidence", 0)

        # Plan confidence + grounding aggregation (mirrors orchestrator path)
        memo_data["plan_confidence"] = int(plan_data.get("plan_confidence", 0) or 0)
        memo_data["plan_confidence_reason"] = plan_data.get("plan_confidence_reason", "") or ""

        # Plan shape + macro context surfaced for the UI
        memo_data["question_type"] = plan_data.get("question_type", "alpha_finding")
        memo_data["benchmark"] = plan_data.get("benchmark", "")
        memo_data["instrument_preference"] = plan_data.get("instrument_preference", "stock")
        memo_data["idea_archetype"] = plan_data.get("idea_archetype", []) or []
        memo_data["sub_questions"] = plan_data.get("sub_questions", []) or []
        memo_data["falsification_criteria"] = plan_data.get("falsification_criteria", []) or []
        memo_data["regime_sensitivity"] = plan_data.get("regime_sensitivity", []) or []
        memo_data["macro_context"] = macro_context_for_interp or {}
        memo_data["secondary_universe"] = plan_data.get("secondary_universe", []) or []
        memo_data["target_idea_count"] = int(plan_data.get("target_idea_count", 10) or 10)
        memo_data["required_style_labels"] = plan_data.get("required_style_labels", []) or []

        # Phase E — thread metadata propagated from the loaded thread_ctx
        memo_data["thread_id"] = thread_ctx.get("thread_id") if thread_ctx else None
        memo_data["parent_memo_id"] = thread_ctx.get("parent_memo_id") if thread_ctx else None
        memo_data["sequence_in_thread"] = int(thread_ctx.get("sequence", 0) or 0) if thread_ctx else 0
        memo_data["query_class"] = plan_data.get("query_class", "fresh")

        # Quality + structural integrity signals
        if isinstance(research_data, dict):
            memo_data["sub_question_coverage"] = research_data.get("sub_question_coverage", []) or []
            if research_data.get("sub_question_answered_pct") is not None:
                memo_data["sub_question_answered_pct"] = research_data.get("sub_question_answered_pct")
        if isinstance(strategy_data, dict):
            memo_data["diversity"] = strategy_data.get("_diversity") or {}
        if isinstance(risk_data, dict):
            memo_data["falsification_probabilities"] = risk_data.get("falsification_probabilities", []) or []
        # Data quality flag based on which desks degraded
        if isinstance(research_data, dict) and "failed" in (research_data.get("data_summary") or "").lower():
            memo_data["data_quality"] = "critical"
        elif isinstance(research_data, dict) and "timed out" in (research_data.get("data_summary") or "").lower():
            memo_data["data_quality"] = "degraded"
        else:
            memo_data["data_quality"] = "complete"

        try:
            rank = {"low": 0, "medium": 1, "high": 2, "n/a": 3}
            pieces = []
            for d in (research_data, risk_data, strategy_data):
                g = (d or {}).get("_grounding") if isinstance(d, dict) else None
                if g:
                    pieces.append(g)
            if pieces:
                worst = min(pieces, key=lambda x: rank.get(x.get("confidence", "n/a"), 3))
                memo_data["grounding"] = {
                    "confidence": worst.get("confidence", "n/a"),
                    "numeric_claims": sum(p.get("numeric_claims", 0) or 0 for p in pieces),
                    "ungrounded_count": sum(p.get("ungrounded_count", 0) or 0 for p in pieces),
                    "desk_count": len(pieces),
                }
        except Exception as e:
            logger.debug(f"[stream] grounding aggregation skipped: {e}")

        # === Phase 1/2 provenance + NLP (Build Plan) ===
        # The streaming path used to skip this entirely — THE reason citations
        # never appeared. We now run the NLP conviction tilt, build the Fact
        # Sheet, attach citations deterministically, and persist evidence —
        # mirroring the orchestrator path so streaming and non-streaming match.
        from config import settings as _prov_settings
        nlp_receipts: list = []
        try:
            if _prov_settings.FILING_NLP_ENABLED or _prov_settings.TRANSCRIPT_NLP_ENABLED:
                from agents.nlp.runner import gather_nlp_signals, apply_nlp_tilt_to_ideas
                yield send({"type": "desk_start", "desk": "nlp", "label": "NLP Signals",
                            "agent": "nlp_signals"})
                _bundle = await gather_nlp_signals(plan_data.get("tickers", []) or [])
                _ideas = memo_data.get("trade_ideas") or []
                if _ideas and _bundle["signals"]:
                    _ideas, _adj = apply_nlp_tilt_to_ideas(_ideas, _bundle["by_ticker_tilt"])
                    memo_data["trade_ideas"] = _ideas
                    memo_data["nlp_adjustments"] = _adj
                nlp_receipts = list(_bundle.get("receipts") or [])
                for _sig in _bundle.get("signals") or []:
                    yield send({"type": "nlp_signal", "desk": "nlp", "ticker": _sig.ticker,
                                "signal": _sig.signal_name, "direction": _sig.direction,
                                "value": round(_sig.value, 3), "confidence": _sig.confidence,
                                "model": _sig.model})
                _cov = _bundle.get("coverage") or {}
                yield send({"type": "desk_done", "desk": "nlp",
                            "summary": f"{len(_bundle.get('signals') or [])} signals · "
                                       f"{_cov.get('covered_pct', 0)}% coverage · "
                                       f"{len(memo_data.get('nlp_adjustments', []))} conviction adj"})
        except Exception as _e:
            logger.warning(f"[stream] NLP signal pass failed (non-fatal): {_e}")

        try:
            if _prov_settings.PROVENANCE_PIPELINE:
                from infra.lineage import extract_tool_lineage
                from pipeline import build_fact_sheet, finalize_with_evidence
                from infra.coverage import compute_coverage, grade_verification
                _lineage = extract_tool_lineage(tool_steps_by_agent)
                memo_data["lineage"] = _lineage
                _fs = build_fact_sheet(
                    macro_context=macro_context_for_interp,
                    strategy_data={"trade_ideas": memo_data.get("trade_ideas") or []},
                    risk_data=risk_data,
                    live_prices=live_prices_for_strategy,
                    lineage=_lineage,
                    extra_receipts=nlp_receipts,
                )
                _fin = finalize_with_evidence(memo_data, _fs)
                memo_data = _fin["memo"]
                memo_data["citation_index"] = _fin["citation_index"]
                memo_data["coverage"] = compute_coverage(memo_data)
                memo_data["verification_status"] = grade_verification(memo_data["coverage"])
                memo_data["evidence_receipts"] = _fs.entries
                memo_data["evidence_links"] = _fin["links"]
                yield send({"type": "provenance", "desk": "cio", "agent": "provenance",
                            "fact_sheet_entries": len(_fs),
                            "citations": len(memo_data.get("citation_index") or []),
                            "verification": memo_data.get("verification_status"),
                            "coverage_pct": (memo_data.get("coverage") or {}).get("citation_coverage_pct")})
        except Exception as _e:
            logger.warning(f"[stream] provenance pipeline failed (non-fatal): {_e}")

        try:
            memo = IntelligenceMemo(**memo_data)
            result = memo.model_dump(mode="json")

            # Persist
            try:
                async with async_session() as session:
                    record = IntelligenceMemoRecord(
                        user_id=user_id,
                        query=memo.query,
                        intent=memo.intent.value if hasattr(memo.intent, "value") else str(memo.intent),
                        title=memo.title,
                        executive_summary=memo.executive_summary,
                        analysis=memo.analysis,
                        key_findings=memo.key_findings,
                        macro_regime=memo.macro_regime,
                        overall_risk_level=memo.overall_risk_level,
                        risk_factors=[rf.model_dump() if hasattr(rf, "model_dump") else rf for rf in memo.risk_factors],
                        trade_ideas=[ti.model_dump() if hasattr(ti, "model_dump") else ti for ti in memo.trade_ideas],
                        portfolio_positioning=memo.portfolio_positioning,
                        hedging_recommendations=memo.hedging_recommendations,
                        tickers_analyzed=memo.tickers_analyzed,
                        themes=memo.themes,
                        lineage=memo.lineage or {},
                        # Phase 1 — claim-level citations + verification
                        citation_index=[
                            c.model_dump() if hasattr(c, "model_dump") else c
                            for c in (memo.citation_index or [])
                        ],
                        coverage=memo.coverage or {},
                        verification_status=memo.verification_status or "unverified",
                        thread_id=memo.thread_id,
                        parent_memo_id=memo.parent_memo_id,
                        sequence_in_thread=memo.sequence_in_thread,
                        thread_summary=memo.thread_summary,
                        query_class=memo.query_class,
                    )
                    session.add(record)
                    await session.commit()
                    # Backfill thread_id to the memo's own id on fresh threads
                    if record.thread_id is None:
                        record.thread_id = record.id
                        await session.commit()
                    result["id"] = record.id
                    result["thread_id"] = record.thread_id
                    result["parent_memo_id"] = record.parent_memo_id
                    result["sequence_in_thread"] = record.sequence_in_thread
                    # Phase 1 — persist evidence receipts + claim links.
                    try:
                        receipts = getattr(memo, "evidence_receipts", None) or []
                        ev_links = getattr(memo, "evidence_links", None) or []
                        if receipts:
                            from provenance import EvidenceRepository
                            hash_to_id = await EvidenceRepository.upsert_many(receipts, user_id=user_id)
                            links = [
                                (l.get("claim_ref"), hash_to_id.get(l.get("content_hash")))
                                for l in ev_links if hash_to_id.get(l.get("content_hash"))
                            ]
                            if links:
                                await EvidenceRepository.link_claims(record.id, links)
                    except Exception as ev_err:
                        logger.warning(f"[stream] evidence persist failed (non-fatal): {ev_err}")
            except Exception as db_err:
                logger.warning(f"[stream] DB persist failed (non-fatal): {db_err}")

            yield send({"phase": "complete", "memo": result})
        except Exception as e:
            logger.error(f"[stream] Memo construction failed: {e}")
            yield send({"phase": "error", "error": f"Memo construction failed: {e}"})

    async def event_stream_with_cleanup():
        """
        Outer wrapper: forwards events, but on client disconnect / generator
        close / cancellation, cancels every agent task still running. Without
        this, a user hitting Cmd+W leaves 4 agents burning through their
        timeouts in the background.
        """
        try:
            async for chunk in event_stream():
                yield chunk
        finally:
            for t in active_tasks:
                if not t.done():
                    t.cancel()
            # Give cancelled tasks a brief window to unwind (mostly benign).
            if active_tasks:
                await asyncio.sleep(0)

    return StreamingResponse(
        event_stream_with_cleanup(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# Legacy ticker endpoint — MUST be after /api/analyze/stream to avoid
# FastAPI matching /api/analyze/{ticker} where ticker="stream"
@app.post("/api/analyze/{ticker}")
async def analyze_ticker(ticker: str):
    """Legacy ticker endpoint — redirects to query-based analysis."""
    return await analyze(AnalyzeRequest(query=f"Deep analysis of {ticker.upper()}"))
