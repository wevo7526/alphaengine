from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import logging

from config import settings
from data.fred_client import FREDDataClient
from data.market_client import MarketDataClient
from data.news_client import NewsDataClient
from data.sec_client import SECDataClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Alpha Engine API", version="2.0.0")

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

# In-memory memo store (Phase 1 — Postgres in Phase 2)
_memo_store: list[dict] = []
_analysis_status: dict[str, dict] = {}


# === HEALTH CHECK ===

@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "env": settings.ENV}


# === ANALYSIS ENDPOINTS ===

class AnalyzeRequest(BaseModel):
    query: str


@app.post("/api/analyze")
async def analyze(request: AnalyzeRequest):
    """Run the full research desk pipeline on a freeform query."""
    from agents.orchestrator import run_research_desk

    query = request.query.strip()
    query_id = str(hash(query + str(len(_memo_store))))
    _analysis_status[query_id] = {"status": "running", "phase": "interpreting"}

    try:
        memo = await run_research_desk(query)
        result = memo.model_dump(mode="json")
        _memo_store.insert(0, result)
        if len(_memo_store) > 100:
            _memo_store.pop()

        _analysis_status[query_id] = {"status": "complete", "phase": "done"}
        return result
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        _analysis_status[query_id] = {"status": "error", "error": str(e)}
        raise HTTPException(status_code=500, detail=f"Analysis failed: {e}")


@app.post("/api/analyze/{ticker}")
async def analyze_ticker(ticker: str):
    """Legacy ticker endpoint — redirects to query-based analysis."""
    return await analyze(AnalyzeRequest(query=f"Deep analysis of {ticker.upper()}"))


@app.get("/api/signals/latest")
async def latest_signals(limit: int = 20):
    """Get most recent intelligence memos."""
    return {"memos": _memo_store[:limit], "count": len(_memo_store[:limit])}


# === DATA ENDPOINTS ===

@app.get("/api/data/macro/snapshot")
async def macro_snapshot():
    """Current macro regime data from FRED."""
    try:
        snapshot = fred_client.get_macro_snapshot()
        return {"indicators": snapshot, "count": len(snapshot)}
    except Exception as e:
        logger.error(f"Macro snapshot failed: {e}")
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


@app.get("/api/quant/enrich")
async def enrich_tickers(tickers: str, period: str = "3mo"):
    """Compute enrichment data for a set of tickers: vol metrics, drawdowns, correlation, price history.
    This is what differentiates from ChatGPT — computed analytics, not prose."""
    from quant.computations import compute_correlation_matrix, compute_drawdown, compute_volatility_metrics
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        raise HTTPException(status_code=400, detail="No tickers provided")

    result: dict = {"tickers": ticker_list, "analytics": {}, "correlation": None}

    # Per-ticker analytics
    for t in ticker_list[:8]:  # Cap at 8 to conserve API
        try:
            vol = compute_volatility_metrics(t, period)
            dd = compute_drawdown(t, period)
            prices = _market_client_for_enrich.get_price_history(t, period="1mo")
            result["analytics"][t] = {
                "volatility": vol,
                "drawdown": dd,
                "sparkline": [{"date": p["date"], "close": p["close"]} for p in prices[-20:]],
            }
        except Exception as e:
            logger.warning(f"Enrichment failed for {t}: {e}")
            result["analytics"][t] = {"error": str(e)}

    # Correlation matrix (only if 2+ tickers)
    if len(ticker_list) >= 2:
        try:
            result["correlation"] = compute_correlation_matrix(ticker_list[:8], period)
        except Exception as e:
            logger.warning(f"Correlation computation failed: {e}")

    return result

# Lazy import for enrichment
from data.market_client import MarketDataClient as _MC
_market_client_for_enrich = _MC()


@app.get("/api/quant/macro-series")
async def macro_time_series():
    """Get macro time series for chart rendering (yield curve, VIX, credit spreads, fed funds)."""
    from quant.computations import get_macro_time_series
    return get_macro_time_series()


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


# === PORTFOLIO ENDPOINTS ===

@app.get("/api/portfolio/positions")
async def portfolio_positions():
    """Current portfolio positions and P&L."""
    return {"positions": [], "total_value": 0, "daily_pnl": 0}


@app.get("/api/portfolio/risk")
async def portfolio_risk():
    """Portfolio-level risk metrics."""
    return {"beta": 0, "var_95": 0, "sector_exposure": {}}


# === WEBSOCKET ===

@app.websocket("/ws/analysis")
async def analysis_stream(websocket: WebSocket):
    """Stream real-time agent updates during analysis."""
    await websocket.accept()
    await websocket.send_json({"type": "connected", "message": "Analysis stream"})
    await websocket.close()
