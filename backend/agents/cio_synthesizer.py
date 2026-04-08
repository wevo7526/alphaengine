"""
CIO Synthesizer — final agent in the pipeline.

Produces the IntelligenceMemo by synthesizing all prior agent outputs.
Pure LLM reasoning — no tool calling.
"""

from langchain_core.messages import SystemMessage, HumanMessage
import json
import logging

from agents.base_agent import get_llm
from agents.schemas import AgentOutput

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the Chief Investment Officer of a quantitative hedge fund. You are
producing the final intelligence memo for the investment committee.

Given all analysis from your team, produce a polished intelligence memo as JSON:

{{
    "title": "<crisp, descriptive title>",
    "executive_summary": "<2-4 sentences. A PM should read just this and know what to do.>",
    "analysis": "<the full research narrative, 3-6 paragraphs. Structure depends on query type.>",
    "key_findings": ["<finding 1 with specific numbers>", "<finding 2>", "<finding 3>"],
    "macro_regime": "<from Risk Manager>",
    "overall_risk_level": "<from Risk Manager>",
    "risk_factors": [<from Risk Manager, include top 3-5>],
    "trade_ideas": [<from Portfolio Strategist, include all>],
    "portfolio_positioning": "<from Portfolio Strategist>",
    "hedging_recommendations": [<from Portfolio Strategist>],
    "tickers_analyzed": [<all tickers that were analyzed>],
    "themes": [<themes from the plan>],
    "intent": "<from the plan>"
}}

Writing standards:
- Write with authority. No "might", "could potentially", "it appears". Commit to views.
- Cite specific numbers: "$257.48", "P/E of 32.6x", "VIX at 25.78", "credit spreads at 312bp".
- Structure the analysis section based on query type:
  * Ticker: Company overview → Financials → Technical setup → Catalysts → Risk/reward
  * Thematic: Theme context → Macro backdrop → Sector analysis → Opportunities → Risks
  * Risk: Regime classification → Risk enumeration → Impact assessment → Hedging
  * Market regime: Regime classification → Key indicators → Outlook → Positioning
- The executive_summary is the most important field. Make it actionable.
- key_findings should be quantitative and specific — not vague observations.

The risk_factors and trade_ideas come from prior agents — include them in the output
as received. Your job is the title, executive_summary, analysis, and key_findings."""

OUTPUT_INSTRUCTIONS = """Respond with a single JSON object matching the schema above.
The analysis field should be the longest — 3-6 substantial paragraphs."""


class CIOSynthesizer:
    agent_name = "cio_synthesizer"

    def __init__(self):
        self.llm = get_llm()

    async def synthesize(self, context: dict) -> AgentOutput:
        """Produce the final IntelligenceMemo from all pipeline outputs."""
        logger.info("[cio_synthesizer] Synthesizing intelligence memo")

        plan = context.get("plan", {})
        research = context.get("research", {})
        risk = context.get("risk", {})
        strategy = context.get("strategy", {})

        user_prompt = (
            f"Original Query: {plan.get('query', '')}\n"
            f"Intent: {plan.get('intent', '')}\n"
            f"Tickers: {', '.join(plan.get('tickers', []))}\n"
            f"Themes: {', '.join(plan.get('themes', []))}\n\n"
            f"=== RESEARCH DATA ===\n{research.get('data_summary', 'No data.')}\n\n"
            f"=== RISK ASSESSMENT ===\n"
            f"Macro Regime: {risk.get('macro_regime', 'unknown')}\n"
            f"Risk Level: {risk.get('overall_risk_level', 'unknown')}\n"
            f"{risk.get('risk_narrative', '')}\n\n"
            f"Risk Factors:\n{json.dumps(risk.get('risk_factors', []), indent=2)}\n\n"
            f"=== PORTFOLIO STRATEGY ===\n"
            f"Positioning: {strategy.get('portfolio_positioning', 'neutral')}\n"
            f"{strategy.get('strategy_narrative', '')}\n\n"
            f"Trade Ideas:\n{json.dumps(strategy.get('trade_ideas', []), indent=2)}\n\n"
            f"Hedging: {json.dumps(strategy.get('hedging_recommendations', []))}\n\n"
            f"Produce the final intelligence memo as JSON."
        )

        try:
            result = await self.llm.ainvoke([
                SystemMessage(content=SYSTEM_PROMPT + "\n\n" + OUTPUT_INSTRUCTIONS),
                HumanMessage(content=user_prompt),
            ])

            text = result.content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
            text = text.strip()

            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                start = text.find("{")
                end = text.rfind("}") + 1
                if start >= 0 and end > start:
                    data = json.loads(text[start:end])
                else:
                    raise

            logger.info(f"[cio_synthesizer] Memo complete: {data.get('title', 'untitled')}")
            return AgentOutput(
                agent_name=self.agent_name,
                output=data,
                reasoning=data.get("executive_summary", ""),
            )
        except Exception as e:
            logger.error(f"[cio_synthesizer] Synthesis failed: {e}")
            return AgentOutput(
                agent_name=self.agent_name,
                output={},
                error=str(e),
            )
