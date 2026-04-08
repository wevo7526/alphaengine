from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select, desc
import logging

from config import settings
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
    await init_db()
    logger.info("Database initialized")
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
    query_id = str(hash(query + str(id(request))))
    _analysis_status[query_id] = {"status": "running", "phase": "interpreting"}

    try:
        memo = await run_research_desk(query)
        result = memo.model_dump(mode="json")

        # Persist to database
        async with async_session() as session:
            record = IntelligenceMemoRecord(
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
            logger.info(f"Memo persisted: {record.id}")

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
    """Get most recent intelligence memos from the database."""
    async with async_session() as session:
        result = await session.execute(
            select(IntelligenceMemoRecord)
            .order_by(desc(IntelligenceMemoRecord.created_at))
            .limit(limit)
        )
        records = result.scalars().all()
        memos = [
            {
                "id": r.id,
                "query": r.query,
                "intent": r.intent,
                "title": r.title,
                "executive_summary": r.executive_summary,
                "macro_regime": r.macro_regime,
                "overall_risk_level": r.overall_risk_level,
                "trade_ideas": r.trade_ideas or [],
                "tickers_analyzed": r.tickers_analyzed or [],
                "themes": r.themes or [],
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in records
        ]
        return {"memos": memos, "count": len(memos)}


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
            prices = _market_client_for_enrich.get_price_history(t, period="1mo")
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
