from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, desc
import json
import asyncio
import logging

from config import settings
from auth import get_user_id
from data.fred_client import FREDDataClient
from data.market_client import MarketDataClient
from data.news_client import NewsDataClient
from data.sec_client import SECDataClient
from db.database import init_db, async_session
from db.models import IntelligenceMemoRecord, ScanFindingRecord, ScanRunRecord, WatchlistRecord

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup."""
    import os
    logger.info(f"Starting Alpha Engine — ENV={settings.ENV}, PORT={os.environ.get('PORT', 'not set')}")
    logger.info(f"DATABASE_URL={'set' if settings.DATABASE_URL else 'empty'} (prefix: {settings.DATABASE_URL[:25]}...)" if settings.DATABASE_URL else "DATABASE_URL=empty")
    try:
        await init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.error(f"Database init failed (non-fatal, app will start): {e}")
    yield


app = FastAPI(title="Alpha Engine API", version="2.0.0", lifespan=lifespan)

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

import time as _time

_analysis_status: dict[str, dict] = {}
_ANALYSIS_STATUS_MAX = 200  # Max entries before cleanup
_ANALYSIS_STATUS_TTL = 3600  # 1 hour


def _cleanup_analysis_status():
    """Evict stale entries from _analysis_status to prevent memory leak."""
    if len(_analysis_status) <= _ANALYSIS_STATUS_MAX:
        return
    now = _time.time()
    stale = [k for k, v in _analysis_status.items() if now - v.get("_ts", 0) > _ANALYSIS_STATUS_TTL]
    for k in stale:
        del _analysis_status[k]
    # If still over limit, remove oldest
    if len(_analysis_status) > _ANALYSIS_STATUS_MAX:
        oldest = sorted(_analysis_status, key=lambda k: _analysis_status[k].get("_ts", 0))
        for k in oldest[:len(_analysis_status) - _ANALYSIS_STATUS_MAX]:
            del _analysis_status[k]


# === HEALTH CHECK ===

@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "env": settings.ENV}


# === ANALYSIS ENDPOINTS ===

class AnalyzeRequest(BaseModel):
    query: str


@app.post("/api/analyze")
async def analyze(request: AnalyzeRequest, req: Request = None):
    """Run the full research desk pipeline on a freeform query."""
    import traceback
    from agents.orchestrator import run_research_desk
    user_id = get_user_id(req) if req else None

    query = request.query.strip()
    query_id = str(hash(query + str(id(request))))
    _cleanup_analysis_status()
    _analysis_status[query_id] = {"status": "running", "phase": "interpreting", "_ts": _time.time()}

    try:
        memo = await run_research_desk(query)
        result = memo.model_dump(mode="json")

        # Persist to database — wrap in try/except so DB errors don't kill the response
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
                )
                session.add(record)
                await session.commit()
                result["id"] = record.id
                logger.info(f"Memo persisted: {record.id} for user {user_id}")
        except Exception as db_err:
            logger.error(f"DB persist failed (non-fatal): {db_err}")

        _analysis_status[query_id] = {"status": "complete", "phase": "done", "_ts": _time.time()}
        return result
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Analysis failed: {e}\n{tb}")
        _analysis_status[query_id] = {"status": "error", "error": str(e), "_ts": _time.time()}
        raise HTTPException(status_code=500, detail=str(e))



@app.get("/api/signals/latest")
async def latest_signals(limit: int = 20, req: Request = None):
    """Get most recent intelligence memos for the current user."""
    try:
        user_id = get_user_id(req) if req else None
        async with async_session() as session:
            query = select(IntelligenceMemoRecord).order_by(desc(IntelligenceMemoRecord.created_at))
            if user_id:
                query = query.where(IntelligenceMemoRecord.user_id == user_id)
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
                }
                for r in records
            ]
            return {"memos": memos, "count": len(memos)}
    except Exception as e:
        logger.error(f"Failed to fetch memos: {e}")
        return {"memos": [], "count": 0}


@app.delete("/api/signals/{memo_id}")
async def delete_memo(memo_id: str, req: Request = None):
    """Delete an intelligence memo by ID. Only the owner can delete."""
    user_id = get_user_id(req) if req else None
    async with async_session() as session:
        result = await session.execute(
            select(IntelligenceMemoRecord).where(IntelligenceMemoRecord.id == memo_id)
        )
        record = result.scalar_one_or_none()
        if not record:
            raise HTTPException(status_code=404, detail="Memo not found")
        # Ownership check: if memo has a user_id, only that user can delete
        if record.user_id and user_id and record.user_id != user_id:
            raise HTTPException(status_code=403, detail="Not authorized to delete this memo")
        await session.delete(record)
        await session.commit()
    return {"deleted": memo_id}


# === DATA ENDPOINTS ===

@app.get("/api/data/macro")
async def macro_dashboard():
    """Consolidated macro endpoint — snapshot + time series in one call."""
    from quant.computations import get_macro_time_series
    from concurrent.futures import ThreadPoolExecutor
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            snapshot_future = pool.submit(fred_client.get_macro_snapshot)
            series_future = pool.submit(get_macro_time_series)
            snapshot = snapshot_future.result()
            series = series_future.result()
        return {
            "indicators": snapshot,
            "count": len(snapshot),
            "series": series,
        }
    except Exception as e:
        logger.error(f"Macro dashboard failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/data/macro/snapshot")
async def macro_snapshot_legacy():
    """Legacy endpoint — use /api/data/macro instead."""
    try:
        snapshot = fred_client.get_macro_snapshot()
        return {"indicators": snapshot, "count": len(snapshot)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/data/market/{ticker}")
async def market_data(ticker: str, period: str = "3mo"):
    """Price history and fundamentals for a ticker."""
    ticker = ticker.upper()
    try:
        fundamentals = market_client.get_fundamentals(ticker)
        price_history = market_client.get_price_history(ticker, period=period)
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
        chain = market_client.get_options_chain(ticker, expiry=expiry)
        return {"ticker": ticker, **chain}
    except Exception as e:
        logger.error(f"Options data failed for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/data/filings/{ticker}")
async def sec_filings(ticker: str, form_type: str = "8-K", limit: int = 5):
    """Recent SEC filings for a ticker."""
    ticker = ticker.upper()
    try:
        filings = sec_client.get_recent_filings(ticker, form_type=form_type, limit=limit)
        return {"ticker": ticker, "form_type": form_type, "filings": filings}
    except Exception as e:
        logger.error(f"SEC filings failed for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/data/news/{ticker}")
async def news_feed(ticker: str):
    """Recent news with sentiment data."""
    ticker = ticker.upper()
    try:
        articles = news_client.get_ticker_news(ticker, page_size=10)
        sentiment = news_client.get_market_sentiment_finnhub(ticker)
        return {
            "ticker": ticker,
            "articles": articles,
            "article_count": len(articles),
            "finnhub_sentiment": sentiment,
        }
    except Exception as e:
        logger.error(f"News feed failed for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
async def portfolio_risk_analysis():
    """Full portfolio risk dashboard: VaR, CVaR, sector exposure, circuit breaker."""
    try:
        from quant.risk import compute_ewma_covariance, compute_portfolio_var, compute_portfolio_cvar, check_sector_limits, drawdown_circuit_breaker
        from quant.computations import compute_drawdown
    except Exception as e:
        logger.error(f"Import error in portfolio-risk: {e}")
        return {"error": str(e), "var_95": None, "cvar_95": None}

    # Get open trades as positions
    try:
        trades = await list_trades_internal("open")
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

    # Compute
    cov = compute_ewma_covariance(returns_dict)
    var_result = compute_portfolio_var(weights, cov, portfolio_value=100000)

    # Portfolio returns for CVaR
    port_returns = []
    min_len = min(len(r) for r in returns_dict.values()) if returns_dict else 0
    for i in range(min_len):
        daily = sum(weights.get(t, 0) * returns_dict[t][i] for t in returns_dict)
        port_returns.append(daily)
    cvar_result = compute_portfolio_cvar(port_returns)

    # Sector check
    sector_result = check_sector_limits(sectors)

    # Drawdown
    dd = compute_drawdown("SPY", "3mo")  # Use SPY as portfolio proxy for now
    circuit = drawdown_circuit_breaker(abs(dd.get("current_drawdown", 0)))

    return {
        **var_result,
        **cvar_result,
        "sector_exposure": sector_result,
        "circuit_breaker": circuit,
        "correlation_matrix": cov,
        "positions_count": len(tickers),
    }


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


# === REGIME DETECTION ===

@app.get("/api/quant/regime")
async def regime_detection():
    """Current macro regime from HMM + rule-based fallback."""
    from quant.regime import classify_regime, fit_regime_model
    snapshot = fred_client.get_macro_snapshot()

    vix = snapshot.get("vix", {}).get("value", 20)
    credit = snapshot.get("credit_spreads", {}).get("value", 3)
    yc = snapshot.get("yield_curve_spread", {}).get("value", 0.5)

    # Try to fit model from FRED history
    try:
        vix_hist = fred_client.get_series_history("VIXCLS", 500)
        credit_hist = fred_client.get_series_history("BAMLH0A0HYM2", 500)
        yc_hist = fred_client.get_series_history("T10Y2Y", 500)

        if vix_hist and credit_hist and yc_hist:
            min_len = min(len(vix_hist), len(credit_hist), len(yc_hist))
            macro_hist = [
                {"date": vix_hist[i]["date"], "vix": vix_hist[i]["value"],
                 "credit_spread": credit_hist[i]["value"], "yield_curve": yc_hist[i]["value"]}
                for i in range(min_len)
            ]
            fit_regime_model(macro_hist)
    except Exception as e:
        logger.warning(f"Regime model fitting failed (using rule-based): {e}")

    return classify_regime(vix, credit, yc)


# === BACKTESTING ===

@app.post("/api/backtest/run")
async def run_backtest(request: dict):
    """Run a rules-based backtest."""
    from quant.backtester import run_rules_based_backtest, BacktestConfig
    from db.repositories import BacktestRepository

    tickers = request.get("tickers", ["AAPL", "MSFT", "GOOGL"])
    period = request.get("period", "1y")
    initial_capital = request.get("initial_capital", 100000)

    # Save run
    run_id = await BacktestRepository.save_run({
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
async def list_backtest_runs():
    """List all backtest runs."""
    from db.repositories import BacktestRepository
    runs = await BacktestRepository.get_runs()
    return {"runs": runs}


@app.get("/api/backtest/results/{run_id}")
async def get_backtest_results(run_id: str):
    """Get results for a specific backtest run."""
    from db.repositories import BacktestRepository
    results = await BacktestRepository.get_results(run_id)
    if not results:
        raise HTTPException(status_code=404, detail="Backtest not found")
    return results


# === FACTOR ANALYSIS ===

@app.get("/api/quant/factors")
async def factor_analysis(tickers: str = "SPY"):
    """Factor loadings and attribution for given tickers."""
    from quant.factors import compute_factor_loadings
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

    # Benchmark
    try:
        spy = market_client.get_price_history("SPY", period="6mo")
        spy_closes = [b["close"] for b in spy]
        benchmark = [(spy_closes[i] - spy_closes[i-1]) / spy_closes[i-1] for i in range(1, len(spy_closes))]
    except Exception as e:
        logger.warning(f"Factor analysis: failed to fetch SPY benchmark: {e}")
        benchmark = []

    if not ticker_returns or not benchmark:
        return {"error": "Insufficient data for factor analysis"}

    # Build equal-weighted portfolio return series aligned to shortest length
    min_len = min(len(r) for r in ticker_returns.values())
    min_len = min(min_len, len(benchmark))
    n_tickers = len(ticker_returns)
    port_returns = []
    for i in range(min_len):
        daily = sum(ticker_returns[t][i] for t in ticker_returns) / n_tickers
        port_returns.append(daily)
    benchmark = benchmark[:min_len]

    loadings = compute_factor_loadings(port_returns, benchmark)

    # Rolling exposures
    from quant.factors import compute_rolling_factor_exposure
    rolling = compute_rolling_factor_exposure(port_returns, benchmark, window=30)

    return {"tickers": ticker_list, **loadings, "rolling_exposures": rolling}


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
async def regime_conditional(ticker: str = "SPY"):
    """Historical average returns of an asset in each regime."""
    from quant.regime import classify_regime, fit_regime_model, get_regime_history, regime_conditional_returns

    # Get macro history for regime classification
    try:
        vix_hist = fred_client.get_series_history("VIXCLS", 500)
        credit_hist = fred_client.get_series_history("BAMLH0A0HYM2", 500)
        yc_hist = fred_client.get_series_history("T10Y2Y", 500)

        min_len = min(len(vix_hist), len(credit_hist), len(yc_hist))
        macro_hist = [
            {"date": vix_hist[i]["date"], "vix": vix_hist[i]["value"],
             "credit_spread": credit_hist[i]["value"], "yield_curve": yc_hist[i]["value"]}
            for i in range(min_len)
        ]
        fit_regime_model(macro_hist)
        regime_hist = get_regime_history(macro_hist)
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
async def morning_report():
    """Get today's morning report. Generates on first access, caches for the day."""
    from db.models import MorningReportRecord
    from datetime import date

    today = date.today().isoformat()

    # Check if already generated today
    async with async_session() as session:
        result = await session.execute(
            select(MorningReportRecord).where(MorningReportRecord.report_date == today)
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
            "and surface 3-5 actionable trade opportunities across sectors."
        )
        report_data = memo.model_dump(mode="json")
        report_data["report_date"] = today

        # Persist
        async with async_session() as session:
            record = MorningReportRecord(
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


@app.post("/api/portfolio/trade")
async def take_trade(req: TakeTradeRequest, request: Request = None):
    """CIO takes a trade idea — persists to trade journal."""
    from db.models import TradeRecord
    user_id = get_user_id(request) if request else None
    async with async_session() as session:
        record = TradeRecord(
            user_id=user_id,
            memo_id=req.memo_id,
            ticker=req.ticker,
            direction=req.direction,
            action=req.action,
            entry_price=req.entry_price,
            stop_loss=req.stop_loss,
            take_profit=req.take_profit,
            position_size_pct=req.position_size_pct,
            conviction=req.conviction,
            thesis=req.thesis,
            md_notes=req.md_notes,
            status="open",
        )
        session.add(record)
        await session.commit()
        return {"id": record.id, "status": "open", "ticker": req.ticker}


class CloseTradeRequest(BaseModel):
    exit_price: float
    notes: str = ""


@app.post("/api/portfolio/trade/{trade_id}/close")
async def close_trade(trade_id: str, req: CloseTradeRequest, request: Request = None):
    """Close an open trade with exit price. Computes realized P&L."""
    from db.models import TradeRecord
    from sqlalchemy import update as sql_update
    user_id = get_user_id(request) if request else None
    async with async_session() as session:
        result = await session.execute(
            select(TradeRecord).where(TradeRecord.id == trade_id)
        )
        trade = result.scalar_one_or_none()
        if not trade:
            raise HTTPException(status_code=404, detail="Trade not found")
        if trade.user_id and user_id and trade.user_id != user_id:
            raise HTTPException(status_code=403, detail="Not authorized to close this trade")
        if trade.status != "open":
            raise HTTPException(status_code=400, detail="Trade already closed")

        # Compute P&L
        entry = trade.entry_price or 0
        is_long = "bullish" in (trade.direction or "")
        if is_long:
            pnl_pct = ((req.exit_price - entry) / entry * 100) if entry > 0 else 0
        else:
            pnl_pct = ((entry - req.exit_price) / entry * 100) if entry > 0 else 0

        from datetime import datetime, timezone
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


@app.get("/api/portfolio/trades")
async def list_trades(status: str = "all", req: Request = None):
    """Get trade journal for current user — open, closed, or all."""
    try:
        from db.models import TradeRecord
        user_id = get_user_id(req) if req else None
        async with async_session() as session:
            query = select(TradeRecord).order_by(desc(TradeRecord.opened_at))
            if user_id:
                query = query.where(TradeRecord.user_id == user_id)
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
async def backtest_trades():
    """Evaluate all open trades against current market prices."""
    from db.models import TradeRecord
    from quant.backtesting import evaluate_trades

    async with async_session() as session:
        result = await session.execute(
            select(TradeRecord).where(TradeRecord.status == "open")
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


@app.get("/api/portfolio/positions")
async def portfolio_positions(req: Request = None):
    """
    Aggregated positions with live P&L.

    Groups open trades by ticker, fetches current prices concurrently,
    computes per-position unrealized P&L, weights, and portfolio summary.
    """
    user_id = get_user_id(req) if req else None
    from db.models import TradeRecord
    from concurrent.futures import ThreadPoolExecutor

    try:
        async with async_session() as session:
            # Open trades for user
            open_q = select(TradeRecord).where(TradeRecord.status == "open")
            if user_id:
                open_q = open_q.where(TradeRecord.user_id == user_id)
            open_result = await session.execute(open_q)
            open_trades = open_result.scalars().all()

            # Closed trades for realized P&L
            closed_q = select(TradeRecord).where(TradeRecord.status != "open")
            if user_id:
                closed_q = closed_q.where(TradeRecord.user_id == user_id)
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

    # Fetch current prices concurrently
    tickers = list({g["ticker"] for g in grouped.values()})

    def _fetch_price(tk: str) -> tuple[str, float | None]:
        try:
            data = market_client.get_fundamentals(tk)
            return tk, data.get("current_price")
        except Exception as e:
            logger.warning(f"Failed to fetch price for {tk}: {e}")
            return tk, None

    prices: dict[str, float | None] = {}
    if tickers:
        with ThreadPoolExecutor(max_workers=4) as pool:
            for ticker, price in pool.map(_fetch_price, tickers):
                prices[ticker] = price

    # Compute per-position metrics
    positions = []
    portfolio_base = 100000.0  # Default portfolio value for % → $ conversion
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
        })

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


# === SCAN / SCREENING DESK ===

_scan_status: dict[str, dict] = {}  # user_id → {status, started_at, run_id}


async def _run_scan_background(user_id: str | None, run_id: str, universe: list[str]):
    """Execute scan, persist findings, update status."""
    from agents.scanner import run_scan
    from datetime import datetime as _dt, timezone as _tz

    try:
        result = run_scan(universe=universe)
        findings = result.get("findings", [])

        async with async_session() as session:
            # Update run record
            run = await session.get(ScanRunRecord, run_id)
            if run:
                run.universe_size = result.get("universe_size", 0)
                run.findings_count = len(findings)
                run.status = "completed"
                run.completed_at = _dt.now(_tz.utc)

            # Persist findings
            for f in findings:
                rec = ScanFindingRecord(
                    user_id=user_id,
                    scan_run_id=run_id,
                    ticker=f.get("ticker", ""),
                    finding_type=f.get("finding_type", "unknown"),
                    priority=f.get("priority", "low"),
                    headline=f.get("headline", "")[:200],
                    detail=f.get("detail", ""),
                    data_json=f.get("data", {}),
                )
                session.add(rec)
            await session.commit()
        logger.info(f"Scan {run_id} completed with {len(findings)} findings")
    except Exception as e:
        logger.error(f"Scan {run_id} failed: {e}")
        try:
            async with async_session() as session:
                run = await session.get(ScanRunRecord, run_id)
                if run:
                    run.status = "failed"
                    run.error_message = str(e)[:500]
                    run.completed_at = _dt.now(_tz.utc)
                    await session.commit()
        except Exception:
            pass
    finally:
        key = user_id or "_anon"
        if key in _scan_status:
            _scan_status[key]["status"] = "idle"


@app.get("/api/scan/latest")
async def scan_latest(req: Request = None):
    """Get findings from the most recent completed scan for the current user."""
    user_id = get_user_id(req) if req else None
    try:
        async with async_session() as session:
            # Find most recent completed run
            runs_q = select(ScanRunRecord).where(
                ScanRunRecord.status == "completed"
            ).order_by(desc(ScanRunRecord.completed_at)).limit(1)
            if user_id:
                runs_q = select(ScanRunRecord).where(
                    ScanRunRecord.status == "completed",
                    (ScanRunRecord.user_id == user_id) | (ScanRunRecord.user_id.is_(None)),
                ).order_by(desc(ScanRunRecord.completed_at)).limit(1)
            run_result = await session.execute(runs_q)
            latest_run = run_result.scalar_one_or_none()

            if not latest_run:
                return {
                    "findings": [],
                    "by_priority": {"high": [], "medium": [], "low": []},
                    "run_id": None,
                    "completed_at": None,
                    "stale": True,
                }

            # Fetch findings for this run
            findings_q = select(ScanFindingRecord).where(
                ScanFindingRecord.scan_run_id == latest_run.id
            )
            f_result = await session.execute(findings_q)
            findings = f_result.scalars().all()

            priority_order = {"high": 0, "medium": 1, "low": 2}
            serialized = [
                {
                    "id": f.id,
                    "ticker": f.ticker,
                    "finding_type": f.finding_type,
                    "priority": f.priority,
                    "headline": f.headline,
                    "detail": f.detail or "",
                    "data": f.data_json or {},
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                }
                for f in findings
            ]
            serialized.sort(key=lambda x: (priority_order.get(x["priority"], 2), x["ticker"]))

            by_priority: dict[str, list[dict]] = {"high": [], "medium": [], "low": []}
            for f in serialized:
                by_priority.setdefault(f["priority"], []).append(f)

            # Determine staleness (> 6 hours old)
            from datetime import datetime as _dt, timezone as _tz, timedelta as _td
            stale = False
            if latest_run.completed_at:
                age = _dt.now(_tz.utc) - latest_run.completed_at.replace(tzinfo=_tz.utc)
                stale = age > _td(hours=6)

            return {
                "findings": serialized,
                "by_priority": by_priority,
                "run_id": latest_run.id,
                "universe_size": latest_run.universe_size,
                "findings_count": latest_run.findings_count,
                "completed_at": latest_run.completed_at.isoformat() if latest_run.completed_at else None,
                "stale": stale,
            }
    except Exception as e:
        logger.error(f"scan_latest failed: {e}")
        return {"findings": [], "by_priority": {"high": [], "medium": [], "low": []}, "run_id": None, "completed_at": None, "stale": True}


@app.post("/api/scan/trigger")
async def scan_trigger(req: Request = None):
    """Trigger a new scan in the background. Returns immediately."""
    user_id = get_user_id(req) if req else None
    key = user_id or "_anon"

    # Don't allow concurrent scans for the same user
    current = _scan_status.get(key, {})
    if current.get("status") == "running":
        return {"status": "already_running", "run_id": current.get("run_id")}

    # Build universe: default + user watchlist + open trade tickers
    from agents.universe import DEFAULT_UNIVERSE
    universe = list(DEFAULT_UNIVERSE)
    try:
        async with async_session() as session:
            # Add watchlist tickers
            wl_q = select(WatchlistRecord)
            if user_id:
                wl_q = wl_q.where(WatchlistRecord.user_id == user_id)
            wl_result = await session.execute(wl_q)
            for rec in wl_result.scalars().all():
                if rec.ticker not in universe:
                    universe.append(rec.ticker)

            # Create run record
            from db.models import TradeRecord
            run = ScanRunRecord(
                user_id=user_id,
                universe_size=len(universe),
                status="running",
            )
            session.add(run)
            await session.commit()
            run_id = run.id
    except Exception as e:
        logger.error(f"scan_trigger setup failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    _scan_status[key] = {"status": "running", "run_id": run_id, "started_at": _time.time()}

    # Fire and forget — run in background task
    asyncio.create_task(_run_scan_background(user_id, run_id, universe))

    return {"status": "started", "run_id": run_id, "universe_size": len(universe)}


@app.get("/api/scan/status")
async def scan_status(req: Request = None):
    """Check if a scan is currently running for this user."""
    user_id = get_user_id(req) if req else None
    key = user_id or "_anon"
    current = _scan_status.get(key, {"status": "idle"})
    return {
        "status": current.get("status", "idle"),
        "run_id": current.get("run_id"),
        "started_at": current.get("started_at"),
    }


# === WATCHLIST ===

class AddWatchlistRequest(BaseModel):
    tickers: list[str]
    notes: str = ""


@app.get("/api/watchlist")
async def watchlist_list(req: Request = None):
    """List the user's watchlist tickers."""
    user_id = get_user_id(req) if req else None
    try:
        async with async_session() as session:
            q = select(WatchlistRecord)
            if user_id:
                q = q.where(WatchlistRecord.user_id == user_id)
            q = q.order_by(desc(WatchlistRecord.added_at))
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
async def watchlist_add(req: AddWatchlistRequest, request: Request = None):
    """Add one or more tickers to the user's watchlist."""
    user_id = get_user_id(request) if request else None
    tickers = [t.strip().upper() for t in req.tickers if t.strip()]
    if not tickers:
        raise HTTPException(status_code=400, detail="No tickers provided")

    added = []
    try:
        async with async_session() as session:
            for ticker in tickers:
                # Skip if already in watchlist
                existing_q = select(WatchlistRecord).where(
                    WatchlistRecord.ticker == ticker,
                )
                if user_id:
                    existing_q = existing_q.where(WatchlistRecord.user_id == user_id)
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
async def watchlist_remove(ticker: str, req: Request = None):
    """Remove a ticker from the user's watchlist."""
    user_id = get_user_id(req) if req else None
    ticker = ticker.strip().upper()
    try:
        async with async_session() as session:
            q = select(WatchlistRecord).where(WatchlistRecord.ticker == ticker)
            if user_id:
                q = q.where(WatchlistRecord.user_id == user_id)
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
async def analyze_stream(request: AnalyzeRequest, req: Request = None):
    """SSE streaming endpoint — sends phase updates as agents complete."""
    from agents.orchestrator import (
        _query_interpreter, _research_analyst, _risk_manager,
        _portfolio_strategist, _cio_synthesizer, _with_timeout,
        IntelligenceMemo,
    )
    user_id = get_user_id(req) if req else None

    query = request.query.strip()

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
            as they arrive. Returns (output, events_yielded_count).
            """
            task = asyncio.create_task(
                asyncio.wait_for(coro_factory(), timeout=timeout_s)
            )
            events_to_yield = []
            last_keepalive = asyncio.get_event_loop().time()

            while not task.done():
                try:
                    # Wait briefly for an event; if none, continue loop
                    event = await asyncio.wait_for(event_queue.get(), timeout=1.5)
                    events_to_yield.append(event)
                except asyncio.TimeoutError:
                    pass

                # Send keepalive if idle too long
                now = asyncio.get_event_loop().time()
                if now - last_keepalive > 10:
                    events_to_yield.append({"_keepalive": True})
                    last_keepalive = now

                if events_to_yield:
                    yield events_to_yield
                    events_to_yield = []

            # Drain any remaining events
            remaining = await drain_queue()
            if remaining:
                yield remaining

            # Get final result
            try:
                result = await task
                yield ("__result__", result)
            except asyncio.TimeoutError:
                logger.error(f"[stream] {label} timed out after {timeout_s}s")
                yield ("__result__", None)
            except Exception as e:
                logger.error(f"[stream] {label} raised: {e}")
                yield ("__result__", None)

        # === Desk 1 (via current Query Interpreter): Intent parsing ===
        yield send({"type": "desk_start", "desk": "query", "label": "Query Interpretation", "agent": "query_interpreter"})
        yield send({"phase": "interpreting", "agent": "query_interpreter"})  # Backward compat
        qi_cb = DeskStreamCallback(event_queue, desk="query", agent="query_interpreter")
        try:
            plan = await _with_timeout(
                _query_interpreter.interpret(query, callbacks=[qi_cb]), seconds=30, label="QI"
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
            yield send({"phase": "interpreting_done", "tickers": plan_data.get("tickers", []), "intent": plan_data.get("intent", "")})
        except Exception as e:
            logger.error(f"[stream] Query Interpreter failed: {e}")
            yield send({"phase": "error", "error": f"Query interpretation failed: {e}"})
            return

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
        try:
            async for chunk in run_with_streaming(
                lambda: _portfolio_strategist.analyze(
                    {"plan": plan_data, "research": research_data, "risk": risk_data}, callbacks=[ps_cb]
                ),
                timeout_s=90, label="PS",
            ):
                if isinstance(chunk, tuple) and chunk[0] == "__result__":
                    output = chunk[1]
                    strategy_data = output.output if output and not output.error else {
                        "trade_ideas": [], "portfolio_positioning": "neutral",
                        "hedging_recommendations": [], "strategy_narrative": "Strategy unavailable.",
                    }
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
        try:
            output = await _with_timeout(
                _cio_synthesizer.synthesize(
                    {"plan": plan_data, "research": research_data, "risk": risk_data, "strategy": strategy_data},
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
                    )
                    session.add(record)
                    await session.commit()
                    result["id"] = record.id
            except Exception as db_err:
                logger.warning(f"[stream] DB persist failed (non-fatal): {db_err}")

            yield send({"phase": "complete", "memo": result})
        except Exception as e:
            logger.error(f"[stream] Memo construction failed: {e}")
            yield send({"phase": "error", "error": f"Memo construction failed: {e}"})

    return StreamingResponse(
        event_stream(),
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
