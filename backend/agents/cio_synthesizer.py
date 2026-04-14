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

Given all analysis from your team, produce ONLY these 4 fields as JSON:

{{
    "title": "<crisp, descriptive title>",
    "executive_summary": "<2-4 sentences. Actionable. A PM reads just this.>",
    "analysis": "<full research narrative, 3-5 paragraphs>",
    "key_findings": ["<finding 1 with numbers>", "<finding 2>", "<finding 3>", "<finding 4>", "<finding 5>"]
}}

DO NOT include risk_factors, trade_ideas, hedging_recommendations, tickers_analyzed,
themes, intent, macro_regime, or overall_risk_level — those are injected separately.
Only output the 4 fields above.

Writing: authoritative, cite specific numbers, no hedging language."""

OUTPUT_INSTRUCTIONS = """Respond with JSON containing ONLY: title, executive_summary, analysis, key_findings."""


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
