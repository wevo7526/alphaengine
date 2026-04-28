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

{
    "title": "<crisp, descriptive title — include the key insight and primary ticker/theme>",
    "executive_summary": "<3-4 sentences. State the recommendation, the conviction level, the key driver, and the primary risk. A PM reads just this and knows what to do.>",
    "analysis": "<MUST be 4-6 substantial paragraphs separated by \\n\\n. Structure as follows:\\n\\nParagraph 1: Macro backdrop — current regime, what it means for the thesis.\\n\\nParagraph 2: Fundamental picture — valuation, margins, growth, balance sheet for the key names. Cite specific numbers (P/E, revenue growth %, margin %).\\n\\nParagraph 3: Technical and sentiment context — price action, momentum, news flow, options positioning.\\n\\nParagraph 4: Risk assessment — what could go wrong, correlation risks, tail scenarios.\\n\\nParagraph 5: Trade construction — how to express the view, why these specific entry/stop/target levels, position sizing rationale.\\n\\nParagraph 6 (optional): Contrarian considerations — what the other side of the trade looks like.>",
    "key_findings": ["<finding 1 — must include a specific number>", "<finding 2 — quantitative>", "<finding 3>", "<finding 4>", "<finding 5>"]
}

DO NOT include risk_factors, trade_ideas, hedging_recommendations, tickers_analyzed,
themes, intent, macro_regime, or overall_risk_level — those are injected separately.

Writing standards:
- Authoritative. No "might", "could", "appears to". Commit to views.
- Every paragraph MUST cite at least 2 specific numbers from the research data.
- Use \\n\\n between paragraphs in the analysis field.
- The analysis field should be 800-1500 words. This is the substance of the memo.
- key_findings must each contain a specific quantitative fact, not vague observations."""

OUTPUT_INSTRUCTIONS = """Respond with JSON containing ONLY: title, executive_summary, analysis, key_findings.
The analysis field MUST be 4-6 paragraphs separated by \\n\\n. Minimum 800 words."""


class CIOSynthesizer:
    agent_name = "cio_synthesizer"

    def __init__(self):
        self.llm = get_llm()

    async def synthesize(self, context: dict, callbacks: list | None = None) -> AgentOutput:
        """Produce the final IntelligenceMemo from all pipeline outputs."""
        logger.info("[cio_synthesizer] Synthesizing intelligence memo")

        plan = context.get("plan", {})
        research = context.get("research", {})
        risk = context.get("risk", {})
        strategy = context.get("strategy", {})
        scorecard = context.get("scorecard") or {}
        prior_memos = context.get("prior_memos") or []

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

        # Adaptive calibration: if we have a scorecard from past signals,
        # surface it so the CIO calibrates conviction based on actual track record.
        # High-IC conviction buckets earn more confidence; low-IC buckets get dampened.
        calibration_block = ""
        if scorecard and scorecard.get("signals", 0) >= 5:
            ic_5d = scorecard.get("ic_5d")
            ic_20d = scorecard.get("ic_20d")
            hr_5d = scorecard.get("hit_rate_5d")
            by_conv = scorecard.get("by_conviction") or {}
            bucket_lines = []
            for bucket, stats in by_conv.items():
                if isinstance(stats, dict) and stats.get("count", 0) > 0:
                    bucket_lines.append(
                        f"  - {bucket}: hit {stats.get('hit_rate_5d', '?')}%, "
                        f"avg ret {stats.get('avg_return_5d', '?')}%, n={stats.get('count', 0)}"
                    )
            calibration_block = (
                f"\n=== TRACK RECORD CALIBRATION ===\n"
                f"Past signals: {scorecard.get('signals', 0)} scored | "
                f"IC 5d: {ic_5d if ic_5d is not None else '—'} | "
                f"IC 20d: {ic_20d if ic_20d is not None else '—'} | "
                f"5d hit rate: {hr_5d if hr_5d is not None else '—'}%\n"
                + ("By conviction bucket:\n" + "\n".join(bucket_lines) if bucket_lines else "")
                + "\nUse this to calibrate conviction levels in this memo. Buckets with weak "
                "track records (hit_rate < 50%, IC < 0.05) should be assigned conservatively. "
                "Strong buckets (hit_rate > 55%, IC > 0.1) earn higher conviction.\n"
            )

        # Continuity block: prior memos that overlap with this query's
        # tickers or themes. CIO is instructed to reconcile current view
        # with past view, not just write fresh prose every time.
        continuity_block = ""
        if prior_memos:
            lines = []
            for m in prior_memos[:3]:
                lines.append(
                    f"- [{m.get('created_at', '?')[:10]}] '{m.get('title', '')[:120]}'\n"
                    f"  Regime then: {m.get('macro_regime', '?')}; "
                    f"Tickers: {', '.join(m.get('tickers', [])[:5])}; "
                    f"Summary: {m.get('executive_summary', '')[:240]}"
                )
            continuity_block = (
                "\n=== PRIOR MEMOS (this user, ticker/theme overlap) ===\n"
                + "\n".join(lines)
                + "\nAcknowledge or reconcile prior view. If thesis has changed, say so explicitly. "
                + "If thesis is unchanged, note continuity (e.g. 'reaffirming our long view from 2 weeks ago').\n"
            )

        user_prompt = (
            f"Query: {plan.get('query', '')}\n"
            f"Intent: {plan.get('intent', '')} | Tickers: {', '.join(plan.get('tickers', []))} | Themes: {', '.join(plan.get('themes', []))}\n\n"
            f"=== RESEARCH ===\n{data_summary}\n\n"
            f"=== RISK ===\nRegime: {risk.get('macro_regime', '?')} | Level: {risk.get('overall_risk_level', '?')}\n"
            f"{risk.get('risk_narrative', '')[:500]}\n{risk_lines}\n\n"
            f"=== TRADE IDEAS ===\nPositioning: {strategy.get('portfolio_positioning', 'neutral')}\n"
            f"{trade_lines}\n\nHedges:\n{hedge_lines}\n"
            f"{calibration_block}"
            f"{continuity_block}\n"
            f"Produce the final intelligence memo as JSON. Include the trade ideas and risk factors as structured objects in your output."
        )

        try:
            config = {"callbacks": callbacks} if callbacks else {}
            result = await self.llm.ainvoke([
                SystemMessage(content=SYSTEM_PROMPT + "\n\n" + OUTPUT_INSTRUCTIONS),
                HumanMessage(content=user_prompt),
            ], config=config)

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
