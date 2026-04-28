"""
Research Desk Orchestrator — LangGraph pipeline for the hedge fund intelligence desk.

Pipeline: Query Interpreter → Research Analyst → Risk Manager → Portfolio Strategist → CIO Synthesizer

Each node receives the full accumulated state from prior agents.
Sequential execution for debuggability and rate-limit friendliness.
"""

from typing import TypedDict
from langgraph.graph import StateGraph, END
import asyncio
import logging

from agents.schemas import (
    AnalysisPlan,
    ResearchData,
    RiskAssessment,
    PortfolioStrategy,
    IntelligenceMemo,
    AgentOutput,
)
from agents.query_interpreter import QueryInterpreter
from agents.research_analyst import ResearchAnalyst
from agents.risk_manager import RiskManager
from agents.portfolio_strategist import PortfolioStrategist
from agents.cio_synthesizer import CIOSynthesizer

logger = logging.getLogger(__name__)

# Singleton agent instances — caches persist across requests
_query_interpreter = QueryInterpreter()
_research_analyst = ResearchAnalyst()
_risk_manager = RiskManager()
_portfolio_strategist = PortfolioStrategist()
_cio_synthesizer = CIOSynthesizer()


class ResearchDeskState(TypedDict):
    query: str
    user_id: str | None
    plan_data: dict | None
    research_data: dict | None
    risk_data: dict | None
    strategy_data: dict | None
    scorecard_data: dict | None
    portfolio_data: dict | None
    memo_data: dict | None
    error: str | None
    current_phase: str


async def _with_timeout(coro, seconds: int, label: str):
    """Wrap an async call with a timeout. Returns None on timeout."""
    try:
        return await asyncio.wait_for(coro, timeout=seconds)
    except asyncio.TimeoutError:
        logger.error(f"[orchestrator] {label} timed out after {seconds}s")
        return None


async def run_interpreter(state: ResearchDeskState) -> ResearchDeskState:
    state["current_phase"] = "interpreting"
    logger.info(f"[orchestrator] Query Interpreter: {state['query']}")
    try:
        plan = await _with_timeout(
            _query_interpreter.interpret(state["query"]),
            seconds=30, label="Query Interpreter"
        )
        if plan:
            state["plan_data"] = plan.model_dump(mode="json")
        else:
            state["error"] = "Query interpretation timed out"
    except Exception as e:
        logger.error(f"[orchestrator] Query Interpreter failed: {e}")
        state["error"] = f"Failed to interpret query: {e}"
    return state


async def run_research(state: ResearchDeskState) -> ResearchDeskState:
    if state.get("error"):
        return state
    state["current_phase"] = "researching"
    logger.info("[orchestrator] Research Analyst gathering data")
    output = await _with_timeout(
        _research_analyst.analyze({"plan": state["plan_data"]}),
        seconds=180, label="Research Analyst"
    )
    if output is None:
        state["research_data"] = {"data_summary": "Research timed out — using limited data."}
    elif output.error:
        logger.warning(f"[orchestrator] Research Analyst error: {output.error}")
        state["research_data"] = {"data_summary": f"Research failed: {output.error}"}
    else:
        state["research_data"] = output.output
    return state


async def run_risk(state: ResearchDeskState) -> ResearchDeskState:
    if state.get("error"):
        return state
    state["current_phase"] = "risk_assessment"
    logger.info("[orchestrator] Risk Manager evaluating")
    output = await _with_timeout(
        _risk_manager.analyze({
            "plan": state["plan_data"],
            "research": state["research_data"],
        }),
        seconds=90, label="Risk Manager"
    )
    if output is None or (output and output.error):
        err = output.error if output else "timed out"
        logger.warning(f"[orchestrator] Risk Manager error: {err}")
        state["risk_data"] = {
            "macro_regime": "unknown",
            "regime_confidence": 0,
            "risk_factors": [],
            "overall_risk_level": "elevated",
            "risk_narrative": f"Risk assessment failed: {err}",
        }
    else:
        state["risk_data"] = output.output
    return state


async def run_strategy(state: ResearchDeskState) -> ResearchDeskState:
    if state.get("error"):
        return state
    state["current_phase"] = "strategizing"
    logger.info("[orchestrator] Portfolio Strategist building trade ideas")

    # Pull portfolio snapshot so Strategist sizes new ideas against the
    # actual book (sector caps, net exposure) rather than in a vacuum.
    if state.get("portfolio_data") is None:
        state["portfolio_data"] = await _fetch_portfolio_snapshot(state.get("user_id"))

    # Pull scorecard early so Strategist can calibrate conviction at the source.
    if state.get("scorecard_data") is None:
        state["scorecard_data"] = await _fetch_scorecard_for_calibration(state.get("user_id"))

    output = await _with_timeout(
        _portfolio_strategist.analyze({
            "plan": state["plan_data"],
            "research": state["research_data"],
            "risk": state["risk_data"],
            "portfolio": state.get("portfolio_data"),
            "scorecard": state.get("scorecard_data"),
        }),
        seconds=90, label="Portfolio Strategist"
    )
    if output is None or (output and output.error):
        err = output.error if output else "timed out"
        logger.warning(f"[orchestrator] Portfolio Strategist error: {err}")
        state["strategy_data"] = {
            "trade_ideas": [],
            "portfolio_positioning": "neutral",
            "hedging_recommendations": [],
            "strategy_narrative": f"Strategy generation failed: {err}",
        }
    else:
        state["strategy_data"] = output.output
    return state


async def _fetch_prior_memos(
    user_id: str | None,
    tickers: list[str] | None,
    themes: list[str] | None,
    limit: int = 3,
) -> list[dict]:
    """
    Look up the user's most recent prior memos that overlap with the current
    plan's tickers or themes. Used by the CIO for narrative continuity:
    "we said this 3 weeks ago — here's how it played out."

    Returns up to `limit` compact dicts: {id, query, title, decision, created_at,
    tickers, themes, executive_summary[:300]}.
    """
    if not user_id:
        return []
    try:
        from sqlalchemy import select, desc, or_
        from db.database import async_session
        from db.models import IntelligenceMemoRecord

        target_tickers = set(t.upper() for t in (tickers or []))
        target_themes = set((t or "").lower() for t in (themes or []))

        async with async_session() as session:
            # Pull recent memos for this user, post-filter for overlap.
            result = await asyncio.wait_for(
                session.execute(
                    select(IntelligenceMemoRecord)
                    .where(IntelligenceMemoRecord.user_id == user_id)
                    .order_by(desc(IntelligenceMemoRecord.created_at))
                    .limit(20)
                ),
                timeout=5.0,
            )
            memos = result.scalars().all()
    except Exception as e:
        logger.debug(f"[orchestrator] prior memos fetch failed (non-fatal): {e}")
        return []

    out: list[dict] = []
    for m in memos:
        memo_tickers = set(t.upper() for t in (m.tickers_analyzed or []))
        memo_themes = set((t or "").lower() for t in (m.themes or []))
        ticker_overlap = bool(target_tickers & memo_tickers)
        theme_overlap = bool(target_themes & memo_themes)
        if not (ticker_overlap or theme_overlap):
            continue
        out.append({
            "id": m.id,
            "query": (m.query or "")[:200],
            "title": (m.title or "")[:160],
            "executive_summary": (m.executive_summary or "")[:400],
            "macro_regime": m.macro_regime,
            "tickers": list(memo_tickers),
            "themes": list(memo_themes),
            "created_at": str(m.created_at) if m.created_at else None,
        })
        if len(out) >= limit:
            break
    return out


async def _fetch_portfolio_snapshot(user_id: str | None) -> dict | None:
    """
    Fetch a compact view of the user's existing open trades so the Strategist
    and CIO can size new ideas against the actual book. Never raises — falls
    back to None for cold-start users.
    """
    if not user_id:
        return None
    try:
        from sqlalchemy import select
        from db.database import async_session
        from db.models import TradeRecord
        from data.sector_map import resolve_sector
        from data.market_client import MarketDataClient

        mc = MarketDataClient()
        async with async_session() as session:
            result = await asyncio.wait_for(
                session.execute(
                    select(TradeRecord).where(
                        TradeRecord.status == "open",
                        TradeRecord.user_id == user_id,
                    )
                ),
                timeout=5.0,
            )
            trades = result.scalars().all()

        positions = []
        for t in trades:
            yahoo_sec = None
            try:
                fund = mc.get_fundamentals(t.ticker)
                yahoo_sec = (fund or {}).get("sector")
            except Exception:
                pass
            sector, _ = resolve_sector(t.ticker, yahoo_sec)
            positions.append({
                "ticker": t.ticker,
                "direction": t.direction,
                "size_pct": float(t.position_size_pct or 0),
                "sector": sector,
            })
        return {"open_positions": positions, "count": len(positions)}
    except Exception as e:
        logger.debug(f"[orchestrator] portfolio snapshot fetch failed (non-fatal): {e}")
        return None


async def _fetch_scorecard_for_calibration(user_id: str | None) -> dict | None:
    """
    Fetch the user's scorecard summary so the CIO can calibrate conviction
    against the system's actual track record. Returns None on any failure —
    the CIO must work without it for cold-start users.
    """
    if not user_id:
        return None
    try:
        from agents.scorer import get_scorecard_summary
        from db.database import async_session
        summary = await asyncio.wait_for(
            get_scorecard_summary(async_session, user_id=user_id),
            timeout=5.0,
        )
        if summary and summary.get("signals", 0) >= 5:
            return summary
    except Exception as e:
        logger.debug(f"[orchestrator] Scorecard fetch failed (non-fatal): {e}")
    return None


async def run_synthesizer(state: ResearchDeskState) -> ResearchDeskState:
    if state.get("error"):
        return state
    state["current_phase"] = "synthesizing"
    logger.info("[orchestrator] CIO Synthesizer writing memo")

    # Adaptive calibration: pull track record before invoking the CIO so it
    # can dampen conviction in low-IC buckets and reinforce high-IC ones.
    scorecard = state.get("scorecard_data")
    if scorecard is None:
        scorecard = await _fetch_scorecard_for_calibration(state.get("user_id"))
        state["scorecard_data"] = scorecard

    # Continuity context: prior memos for any ticker/theme overlap so the
    # CIO can reconcile with the user's existing narrative on this name.
    plan = state.get("plan_data") or {}
    prior_memos = await _fetch_prior_memos(
        state.get("user_id"),
        plan.get("tickers") or [],
        plan.get("themes") or [],
    )

    output = await _with_timeout(
        _cio_synthesizer.synthesize({
            "plan": state["plan_data"],
            "research": state["research_data"],
            "risk": state["risk_data"],
            "strategy": state["strategy_data"],
            "scorecard": scorecard,
            "prior_memos": prior_memos,
        }),
        seconds=120, label="CIO Synthesizer"
    )
    if output is None or (output and output.error):
        err = output.error if output else "timed out"
        logger.warning(f"[orchestrator] CIO failed ({err}) — constructing memo from prior outputs")
        plan = state.get("plan_data", {})
        risk = state.get("risk_data", {})
        strategy = state.get("strategy_data", {})
        research = state.get("research_data", {})
        trade_ideas = strategy.get("trade_ideas", [])
        top_tickers = ", ".join(plan.get("tickers", [])[:4])
        state["memo_data"] = {
            "title": f"Analysis: {plan.get('query', 'Market Analysis')[:80]}",
            "executive_summary": (
                f"Macro regime: {risk.get('macro_regime', 'unknown')}. "
                f"Risk level: {risk.get('overall_risk_level', 'elevated')}. "
                f"{len(trade_ideas)} trade ideas generated for {top_tickers}. "
                f"{strategy.get('strategy_narrative', '')[:300]}"
            ),
            "analysis": research.get("data_summary", ""),
            "key_findings": [risk.get("risk_narrative", "")[:200]] if risk.get("risk_narrative") else [],
        }
    else:
        state["memo_data"] = output.output
    return state


def build_research_desk_graph() -> StateGraph:
    graph = StateGraph(ResearchDeskState)

    graph.add_node("interpreter", run_interpreter)
    graph.add_node("research", run_research)
    graph.add_node("risk", run_risk)
    graph.add_node("strategy", run_strategy)
    graph.add_node("synthesizer", run_synthesizer)

    graph.set_entry_point("interpreter")
    graph.add_edge("interpreter", "research")
    graph.add_edge("research", "risk")
    graph.add_edge("risk", "strategy")
    graph.add_edge("strategy", "synthesizer")
    graph.add_edge("synthesizer", END)

    return graph


_graph = None


def get_research_desk_graph():
    global _graph
    if _graph is None:
        _graph = build_research_desk_graph().compile()
    return _graph


async def run_research_desk(query: str, user_id: str | None = None) -> IntelligenceMemo:
    """Main entry point — run the full research desk pipeline on a freeform query."""
    logger.info(f"[orchestrator] Starting research desk for: {query}")

    graph = get_research_desk_graph()
    initial_state: ResearchDeskState = {
        "query": query,
        "user_id": user_id,
        "plan_data": None,
        "research_data": None,
        "risk_data": None,
        "strategy_data": None,
        "scorecard_data": None,
        "portfolio_data": None,
        "memo_data": None,
        "error": None,
        "current_phase": "idle",
    }

    final_state = await graph.ainvoke(initial_state)

    if final_state.get("error"):
        logger.error(f"[orchestrator] Pipeline failed: {final_state['error']}")
        raise RuntimeError(final_state["error"])

    memo_data = final_state["memo_data"]
    # Merge in fields from prior stages that the CIO might not have echoed
    plan = final_state.get("plan_data", {})
    risk = final_state.get("risk_data", {})
    strategy = final_state.get("strategy_data", {})

    # CIO Synthesizer writes title, executive_summary, analysis, key_findings.
    # Structured data (risk_factors, trade_ideas, hedges) comes from prior agents
    # directly — don't trust the LLM to reconstruct structured objects from compressed text.
    memo_data["query"] = query
    memo_data["intent"] = plan.get("intent", "thematic_research")
    memo_data["tickers_analyzed"] = plan.get("tickers", [])
    memo_data["themes"] = plan.get("themes", [])
    memo_data["macro_regime"] = risk.get("macro_regime", "")
    memo_data["overall_risk_level"] = risk.get("overall_risk_level", "")
    memo_data["risk_factors"] = risk.get("risk_factors", [])  # Always use structured data
    memo_data["trade_ideas"] = strategy.get("trade_ideas", [])  # Always use structured data
    memo_data["portfolio_positioning"] = strategy.get("portfolio_positioning", "")
    memo_data["hedging_recommendations"] = strategy.get("hedging_recommendations", [])

    # Run the Decision Gate (programmatic) using the user's scorecard for
    # track-record-adjusted confidence.
    try:
        from agents.desk5_decision_gate import compute_decision
        decision = compute_decision(
            trade_ideas=strategy.get("trade_ideas", []),
            macro_regime=risk.get("macro_regime", "unknown"),
            overall_risk_level=risk.get("overall_risk_level", "elevated"),
            scorecard=final_state.get("scorecard_data"),
        )
        memo_data["decision"] = decision.get("decision", "WATCH")
        memo_data["decision_reason"] = decision.get("reason", "")
        memo_data["decision_confidence"] = decision.get("confidence", 0)
    except Exception as e:
        logger.warning(f"[orchestrator] Decision gate failed: {e}")

    memo = IntelligenceMemo(**memo_data)
    logger.info(f"[orchestrator] Memo complete: {memo.title}")
    return memo
