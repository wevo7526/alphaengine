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
from db.models import IntelligenceMemoRecord

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
    try:
        snapshot = fred_client.get_macro_snapshot()
        series = get_macro_time_series()
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

    # Per-ticker analytics (cap at 6 to conserve API)
    for t in ticker_list[:6]:
        try:
            vol = compute_volatility_metrics(t, period)
            dd = compute_drawdown(t, period)
            prices = market_client.get_price_history(t, period="1mo")
            options = analyze_options(t)
            # Sentiment scoring
            articles = news_client.get_ticker_news(t, page_size=10)
            sentiment = score_articles(articles)
            result["analytics"][t] = {
                "volatility": vol,
                "drawdown": dd,
                "sparkline": [{"date": p["date"], "close": p["close"]} for p in prices[-20:]],
                "options": options if "error" not in options else None,
                "sentiment": sentiment.get("aggregate"),
            }
        except Exception as e:
            logger.warning(f"Enrichment failed for {t}: {e}")
            result["analytics"][t] = {"error": str(e)}

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

        # Phase 1: Interpret
        yield send({"phase": "interpreting", "agent": "query_interpreter"})
        try:
            plan = await _with_timeout(
                _query_interpreter.interpret(query), seconds=30, label="QI"
            )
            if not plan:
                yield send({"phase": "error", "error": "Query interpretation timed out"})
                return
            plan_data = plan.model_dump(mode="json")
            yield send({"phase": "interpreting_done", "tickers": plan_data.get("tickers", []), "intent": plan_data.get("intent", "")})
        except Exception as e:
            logger.error(f"[stream] Query Interpreter failed: {e}")
            yield send({"phase": "error", "error": f"Query interpretation failed: {e}"})
            return

        # Phase 2: Research (longest phase — send keepalives)
        yield send({"phase": "researching", "agent": "research_analyst"})
        try:
            output = await _with_timeout(
                _research_analyst.analyze({"plan": plan_data}), seconds=180, label="RA"
            )
            research_data = output.output if output and not output.error else {"data_summary": "Research unavailable."}
        except Exception as e:
            logger.error(f"[stream] Research Analyst failed: {e}")
            research_data = {"data_summary": f"Research failed: {e}"}
        yield keepalive()
        yield send({"phase": "researching_done"})

        # Phase 3: Risk
        yield send({"phase": "risk_assessment", "agent": "risk_manager"})
        try:
            output = await _with_timeout(
                _risk_manager.analyze({"plan": plan_data, "research": research_data}),
                seconds=90, label="RM"
            )
            risk_data = output.output if output and not output.error else {
                "macro_regime": "unknown", "regime_confidence": 0,
                "risk_factors": [], "overall_risk_level": "elevated",
                "risk_narrative": "Risk assessment unavailable.",
            }
        except Exception as e:
            logger.error(f"[stream] Risk Manager failed: {e}")
            risk_data = {
                "macro_regime": "unknown", "regime_confidence": 0,
                "risk_factors": [], "overall_risk_level": "elevated",
                "risk_narrative": f"Risk assessment failed: {e}",
            }
        yield keepalive()
        yield send({"phase": "risk_assessment_done", "macro_regime": risk_data.get("macro_regime", "")})

        # Phase 4: Strategy
        yield send({"phase": "strategizing", "agent": "portfolio_strategist"})
        try:
            output = await _with_timeout(
                _portfolio_strategist.analyze({"plan": plan_data, "research": research_data, "risk": risk_data}),
                seconds=90, label="PS"
            )
            strategy_data = output.output if output and not output.error else {
                "trade_ideas": [], "portfolio_positioning": "neutral",
                "hedging_recommendations": [], "strategy_narrative": "Strategy unavailable.",
            }
        except Exception as e:
            logger.error(f"[stream] Portfolio Strategist failed: {e}")
            strategy_data = {
                "trade_ideas": [], "portfolio_positioning": "neutral",
                "hedging_recommendations": [], "strategy_narrative": f"Strategy failed: {e}",
            }
        yield keepalive()
        yield send({"phase": "strategizing_done", "trade_count": len(strategy_data.get("trade_ideas", []))})

        # Phase 5: Synthesize
        yield send({"phase": "synthesizing", "agent": "cio_synthesizer"})
        try:
            output = await _with_timeout(
                _cio_synthesizer.synthesize({"plan": plan_data, "research": research_data, "risk": risk_data, "strategy": strategy_data}),
                seconds=90, label="CIO"
            )
            memo_data = output.output if output and not output.error else {"title": "Analysis incomplete", "executive_summary": "", "analysis": "", "key_findings": []}
        except Exception as e:
            logger.error(f"[stream] CIO Synthesizer failed: {e}")
            memo_data = {"title": "Analysis incomplete", "executive_summary": str(e), "analysis": "", "key_findings": []}

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
