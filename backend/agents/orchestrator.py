"""
Research Desk Orchestrator — LangGraph pipeline for the hedge fund intelligence desk.

Pipeline: Query Interpreter → Research Analyst → Risk Manager → Portfolio Strategist → CIO Synthesizer

Each node receives the full accumulated state from prior agents.
Sequential execution for debuggability and rate-limit friendliness.
"""

from typing import TypedDict
from langgraph.graph import StateGraph, END
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


async def run_interpreter(state: ResearchDeskState) -> ResearchDeskState:
    state["current_phase"] = "interpreting"
    logger.info(f"[orchestrator] Query Interpreter: {state['query']}")
    try:
        plan = await _query_interpreter.interpret(state["query"])
        state["plan_data"] = plan.model_dump(mode="json")
    except Exception as e:
        logger.error(f"[orchestrator] Query Interpreter failed: {e}")
        state["error"] = f"Failed to interpret query: {e}"
    return state


async def run_research(state: ResearchDeskState) -> ResearchDeskState:
    if state.get("error"):
        return state
    state["current_phase"] = "researching"
    logger.info("[orchestrator] Research Analyst gathering data")
    output = await _research_analyst.analyze({"plan": state["plan_data"]})
    if output.error:
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
    output = await _risk_manager.analyze({
        "plan": state["plan_data"],
        "research": state["research_data"],
    })
    if output.error:
        logger.warning(f"[orchestrator] Risk Manager error: {output.error}")
        state["risk_data"] = {
            "macro_regime": "unknown",
            "regime_confidence": 0,
            "risk_factors": [],
            "overall_risk_level": "elevated",
            "risk_narrative": f"Risk assessment failed: {output.error}",
        }
    else:
        state["risk_data"] = output.output
    return state


async def run_strategy(state: ResearchDeskState) -> ResearchDeskState:
    if state.get("error"):
        return state
    state["current_phase"] = "strategizing"
    logger.info("[orchestrator] Portfolio Strategist building trade ideas")
    output = await _portfolio_strategist.analyze({
        "plan": state["plan_data"],
        "research": state["research_data"],
        "risk": state["risk_data"],
    })
    if output.error:
        logger.warning(f"[orchestrator] Portfolio Strategist error: {output.error}")
        state["strategy_data"] = {
            "trade_ideas": [],
            "portfolio_positioning": "neutral",
            "hedging_recommendations": [],
            "strategy_narrative": f"Strategy generation failed: {output.error}",
        }
    else:
        state["strategy_data"] = output.output
    return state


async def run_synthesizer(state: ResearchDeskState) -> ResearchDeskState:
    if state.get("error"):
        return state
    state["current_phase"] = "synthesizing"
    logger.info("[orchestrator] CIO Synthesizer writing memo")
    output = await _cio_synthesizer.synthesize({
        "plan": state["plan_data"],
        "research": state["research_data"],
        "risk": state["risk_data"],
        "strategy": state["strategy_data"],
    })
    if output.error:
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

    memo_data.setdefault("query", query)
    memo_data.setdefault("intent", plan.get("intent", "thematic_research"))
    memo_data.setdefault("tickers_analyzed", plan.get("tickers", []))
    memo_data.setdefault("themes", plan.get("themes", []))
    memo_data.setdefault("macro_regime", risk.get("macro_regime", ""))
    memo_data.setdefault("overall_risk_level", risk.get("overall_risk_level", ""))
    memo_data.setdefault("risk_factors", risk.get("risk_factors", []))
    memo_data.setdefault("trade_ideas", strategy.get("trade_ideas", []))
    memo_data.setdefault("portfolio_positioning", strategy.get("portfolio_positioning", ""))
    memo_data.setdefault("hedging_recommendations", strategy.get("hedging_recommendations", []))

    memo = IntelligenceMemo(**memo_data)
    logger.info(f"[orchestrator] Memo complete: {memo.title}")
    return memo
