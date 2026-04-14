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
    plan_data: dict | None
    research_data: dict | None
    risk_data: dict | None
    strategy_data: dict | None
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
        seconds=120, label="Research Analyst"
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
        seconds=60, label="Risk Manager"
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
    output = await _with_timeout(
        _portfolio_strategist.analyze({
            "plan": state["plan_data"],
            "research": state["research_data"],
            "risk": state["risk_data"],
        }),
        seconds=60, label="Portfolio Strategist"
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


async def run_synthesizer(state: ResearchDeskState) -> ResearchDeskState:
    if state.get("error"):
        return state
    state["current_phase"] = "synthesizing"
    logger.info("[orchestrator] CIO Synthesizer writing memo")
    output = await _with_timeout(
        _cio_synthesizer.synthesize({
            "plan": state["plan_data"],
            "research": state["research_data"],
            "risk": state["risk_data"],
            "strategy": state["strategy_data"],
        }),
        seconds=60, label="CIO Synthesizer"
    )
    if output is None:
        state["error"] = "Memo synthesis timed out"
    elif output.error:
        state["error"] = f"Memo synthesis failed: {output.error}"
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


async def run_research_desk(query: str) -> IntelligenceMemo:
    """Main entry point — run the full research desk pipeline on a freeform query."""
    logger.info(f"[orchestrator] Starting research desk for: {query}")

    graph = get_research_desk_graph()
    initial_state: ResearchDeskState = {
        "query": query,
        "plan_data": None,
        "research_data": None,
        "risk_data": None,
        "strategy_data": None,
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

    memo = IntelligenceMemo(**memo_data)
    logger.info(f"[orchestrator] Memo complete: {memo.title}")
    return memo
