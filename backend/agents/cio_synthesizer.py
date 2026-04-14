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

        # Compress risk factors to one-liners instead of full JSON
        risk_factors = risk.get("risk_factors", [])
        risk_lines = "\n".join(
            f"- [{rf.get('severity','?')}/{rf.get('category','?')}] {rf.get('description','')[:100]}"
            for rf in (risk_factors[:5] if isinstance(risk_factors, list) else [])
        )

        # Compress trade ideas to one-liners instead of full JSON
        trade_ideas = strategy.get("trade_ideas", [])
        trade_lines = "\n".join(
            f"- {ti.get('ticker','?')} {ti.get('direction','?')} (conv:{ti.get('conviction','?')}) "
            f"entry:{ti.get('entry_zone','?')} stop:{ti.get('stop_loss','?')} "
            f"target:{ti.get('take_profit','?')} | {ti.get('thesis','')[:80]}"
            for ti in (trade_ideas[:5] if isinstance(trade_ideas, list) else [])
        )

        hedges = strategy.get("hedging_recommendations", [])
        hedge_lines = "\n".join(f"- {h[:120]}" for h in (hedges[:5] if isinstance(hedges, list) else []))

        # Trim research summary to 2000 chars max
        data_summary = research.get("data_summary", "No data.")
        if len(data_summary) > 2000:
            data_summary = data_summary[:2000] + "..."

        user_prompt = (
            f"Query: {plan.get('query', '')}\n"
            f"Intent: {plan.get('intent', '')} | Tickers: {', '.join(plan.get('tickers', []))} | Themes: {', '.join(plan.get('themes', []))}\n\n"
            f"=== RESEARCH ===\n{data_summary}\n\n"
            f"=== RISK ===\nRegime: {risk.get('macro_regime', '?')} | Level: {risk.get('overall_risk_level', '?')}\n"
            f"{risk.get('risk_narrative', '')[:500]}\n{risk_lines}\n\n"
            f"=== TRADE IDEAS ===\nPositioning: {strategy.get('portfolio_positioning', 'neutral')}\n"
            f"{trade_lines}\n\nHedges:\n{hedge_lines}\n\n"
            f"Produce the final intelligence memo as JSON. Include the trade ideas and risk factors as structured objects in your output."
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
