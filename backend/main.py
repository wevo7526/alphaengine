from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, desc
import json
import asyncio
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
    import traceback
    from agents.orchestrator import run_research_desk

    query = request.query.strip()
    query_id = str(hash(query + str(id(request))))
    _analysis_status[query_id] = {"status": "running", "phase": "interpreting"}

    try:
        memo = await run_research_desk(query)
        result = memo.model_dump(mode="json")

        # Persist to database — wrap in try/except so DB errors don't kill the response
        try:
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
        except Exception as db_err:
            logger.error(f"DB persist failed (non-fatal): {db_err}")

        _analysis_status[query_id] = {"status": "complete", "phase": "done"}
        return result
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"Analysis failed: {e}\n{tb}")
        _analysis_status[query_id] = {"status": "error", "error": str(e)}
        raise HTTPException(status_code=500, detail=str(e))


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
async def take_trade(req: TakeTradeRequest):
    """CIO takes a trade idea — persists to trade journal."""
    from db.models import TradeRecord
    async with async_session() as session:
        record = TradeRecord(
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


@app.get("/api/portfolio/trades")
async def list_trades(status: str = "all"):
    """Get trade journal — open, closed, or all."""
    from db.models import TradeRecord
    async with async_session() as session:
        query = select(TradeRecord).order_by(desc(TradeRecord.opened_at))
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
    """Portfolio-level risk metrics."""
    return {"beta": 0, "var_95": 0, "sector_exposure": {}}


# === STREAMING ANALYSIS ===

@app.post("/api/analyze/stream")
async def analyze_stream(request: AnalyzeRequest):
    """SSE streaming endpoint — sends phase updates as agents complete."""
    from agents.orchestrator import (
        _query_interpreter, _research_analyst, _risk_manager,
        _portfolio_strategist, _cio_synthesizer, _with_timeout,
        IntelligenceMemo,
    )

    query = request.query.strip()

    async def event_stream():
        def send(data: dict) -> str:
            return f"data: {json.dumps(data)}\n\n"

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
            yield send({"phase": "error", "error": str(e)})
            return

        # Phase 2: Research
        yield send({"phase": "researching", "agent": "research_analyst"})
        output = await _with_timeout(
            _research_analyst.analyze({"plan": plan_data}), seconds=120, label="RA"
        )
        research_data = output.output if output and not output.error else {"data_summary": "Research unavailable."}
        yield send({"phase": "researching_done"})

        # Phase 3: Risk
        yield send({"phase": "risk_assessment", "agent": "risk_manager"})
        output = await _with_timeout(
            _risk_manager.analyze({"plan": plan_data, "research": research_data}),
            seconds=60, label="RM"
        )
        risk_data = output.output if output and not output.error else {
            "macro_regime": "unknown", "regime_confidence": 0,
            "risk_factors": [], "overall_risk_level": "elevated",
            "risk_narrative": "Risk assessment unavailable.",
        }
        yield send({"phase": "risk_assessment_done", "macro_regime": risk_data.get("macro_regime", "")})

        # Phase 4: Strategy
        yield send({"phase": "strategizing", "agent": "portfolio_strategist"})
        output = await _with_timeout(
            _portfolio_strategist.analyze({"plan": plan_data, "research": research_data, "risk": risk_data}),
            seconds=60, label="PS"
        )
        strategy_data = output.output if output and not output.error else {
            "trade_ideas": [], "portfolio_positioning": "neutral",
            "hedging_recommendations": [], "strategy_narrative": "Strategy unavailable.",
        }
        yield send({"phase": "strategizing_done", "trade_count": len(strategy_data.get("trade_ideas", []))})

        # Phase 5: Synthesize
        yield send({"phase": "synthesizing", "agent": "cio_synthesizer"})
        output = await _with_timeout(
            _cio_synthesizer.synthesize({"plan": plan_data, "research": research_data, "risk": risk_data, "strategy": strategy_data}),
            seconds=60, label="CIO"
        )
        memo_data = output.output if output and not output.error else {"title": "Analysis incomplete", "executive_summary": "", "analysis": "", "key_findings": []}

        # Inject structured data
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
            except Exception:
                pass

            yield send({"phase": "complete", "memo": result})
        except Exception as e:
            yield send({"phase": "error", "error": str(e)})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
