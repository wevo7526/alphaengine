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
        macro = context.get("macro_context") or {}

        # Risk factors — full structured form, no aggressive truncation.
        # Each line keeps category, severity, description, mitigation so CIO
        # can write substantively without reverse-engineering from a one-liner.
        risk_factors = risk.get("risk_factors", [])
        risk_lines = "\n".join(
            f"- [{rf.get('severity','?')}/{rf.get('category','?')}] {rf.get('description','')[:280]} "
            f"(mitigation: {rf.get('mitigation','')[:140]})"
            for rf in (risk_factors[:6] if isinstance(risk_factors, list) else [])
        )

        # Trade ideas — full structured form. CIO needs the actual thesis,
        # not a 80-char skeleton, to write coherent memo paragraphs.
        trade_ideas = strategy.get("trade_ideas", [])
        trade_lines = "\n".join(
            f"- {ti.get('ticker','?')} {ti.get('direction','?')} (conv:{ti.get('conviction','?')}) "
            f"entry:{ti.get('entry_zone','?')} stop:{ti.get('stop_loss','?')} "
            f"target:{ti.get('take_profit','?')} R/R:{ti.get('risk_reward_ratio','?')} "
            f"size:{ti.get('position_size_pct','?')}%\n"
            f"  Thesis: {ti.get('thesis','')}\n"
            f"  Catalysts: {' · '.join((ti.get('catalysts') or [])[:3])}\n"
            f"  Risks: {' · '.join((ti.get('risks') or [])[:3])}"
            for ti in (trade_ideas[:5] if isinstance(trade_ideas, list) else [])
        )

        hedges = strategy.get("hedging_recommendations", [])
        hedge_lines = "\n".join(f"- {h}" for h in (hedges[:5] if isinstance(hedges, list) else []))

        # Research summary — keep full prose; trim only at 4000 chars (was 2000)
        # so the CIO can actually read the analysis instead of a teaser.
        data_summary = research.get("data_summary", "No data.")
        if len(data_summary) > 4000:
            data_summary = data_summary[:4000] + "..."

        # Sub-question coverage — show the CIO which questions Research
        # actually answered so it can cite them by name (Q1/Q2/...) and
        # explicitly flag any that went unanswered.
        sub_q_block = ""
        sub_qs = plan.get("sub_questions") or []
        coverage = research.get("sub_question_coverage") or []
        if sub_qs:
            cov_map = {c.get("question"): c.get("answered") for c in coverage if isinstance(c, dict)}
            lines = []
            for i, q in enumerate(sub_qs, start=1):
                marker = "✓" if cov_map.get(q) else "?"
                lines.append(f"  Q{i} [{marker}]: {q}")
            sub_q_block = (
                "\n=== SUB-QUESTIONS THE PLAN REQUIRED ===\n"
                + "\n".join(lines)
                + "\nCITE these by name (Q1/Q2/...) in your analysis. If a question went "
                "unanswered, state so explicitly and explain what data was missing.\n"
            )

        # Falsification block — what would change the view. CIO must address
        # this in the memo so the user sees the trade thesis is invalidatable.
        falsification = plan.get("falsification_criteria") or []
        falsif_probs = (risk or {}).get("falsification_probabilities") or []
        prob_map: dict[str, str] = {}
        for fp in falsif_probs:
            if isinstance(fp, dict) and fp.get("criterion"):
                prob_map[fp["criterion"]] = fp.get("probability", "medium")
        falsification_block = ""
        if falsification:
            lines = []
            for c in falsification:
                p = prob_map.get(c, "medium")
                lines.append(f"  [{p}] {c}")
            falsification_block = (
                "\n=== FALSIFICATION CRITERIA (what would change our view) ===\n"
                + "\n".join(lines)
                + "\nDevote a paragraph to 'what would change our view' citing 2-3 of these.\n"
            )

        # Macro backdrop — opening paragraph of the analysis must tie to the
        # home-page indicators (yield curve, credit spreads, VIX, fed funds)
        # so the user sees the systematic-vs-idiosyncratic decomposition.
        macro_block = ""
        if macro:
            lines = ["\n=== MACRO BACKDROP (open the analysis with this context) ==="]
            if macro.get("current_regime"):
                lines.append(f"  Regime: {macro['current_regime']} (confidence {macro.get('confidence', '?')})")
            if macro.get("vix") is not None:
                lines.append(f"  VIX: {macro['vix']}")
            if macro.get("credit_spreads") is not None:
                lines.append(f"  HY credit spread: {macro['credit_spreads']}")
            if macro.get("yield_curve") is not None:
                lines.append(f"  Yield curve (10Y-2Y): {macro['yield_curve']}")
            if macro.get("fed_funds_rate") is not None:
                lines.append(f"  Fed funds rate: {macro['fed_funds_rate']}")
            lines.append(
                "Open paragraph 1 of the analysis with this regime + indicators "
                "so the reader sees the beta context before the alpha thesis."
            )
            macro_block = "\n".join(lines) + "\n"

        # Plan-shape block — surface question_type, instrument_preference,
        # idea_archetype, benchmark so the CIO frames the memo correctly.
        plan_shape_block = (
            f"\n=== PLAN SHAPE ===\n"
            f"  Question type: {plan.get('question_type', 'alpha_finding')}\n"
            f"  Instrument preference: {plan.get('instrument_preference', 'stock')}\n"
            f"  Benchmark: {plan.get('benchmark') or 'SPY (default)'}\n"
            f"  Idea archetype: {plan.get('idea_archetype') or '[]'}\n"
            f"  Plan confidence: {plan.get('plan_confidence', '?')} ({plan.get('plan_confidence_reason', '')})\n"
        )

        # Adaptive calibration: scorecard track record. Compact one-liner
        # plus bucket roll-up to keep prompt tight.
        calibration_block = ""
        if scorecard and scorecard.get("signals", 0) >= 5:
            ic_5d = scorecard.get("ic_5d")
            hr_5d = scorecard.get("hit_rate_5d")
            by_conv = scorecard.get("by_conviction") or {}
            bucket_summary_parts = []
            for bucket, stats in by_conv.items():
                if isinstance(stats, dict) and stats.get("count", 0) > 0:
                    bucket_summary_parts.append(f"{bucket}={stats.get('hit_rate_5d', '?')}%")
            calibration_block = (
                f"\n=== TRACK RECORD ===\n"
                f"n={scorecard.get('signals', 0)} | hit5d={hr_5d}% | IC5d={ic_5d}"
                + (f" | by conviction: {', '.join(bucket_summary_parts)}" if bucket_summary_parts else "")
                + "\nCalibrate conviction: dampen weak buckets (<50% hit), reinforce strong (>55%).\n"
            )

        # Continuity block: prior memos that overlap with this query's
        # tickers or themes. CIO is instructed to reconcile current view
        # with past view, not just write fresh prose every time.
        # Cap at 2 memos × 200 chars to keep prompt under control.
        continuity_block = ""
        if prior_memos:
            lines = []
            for m in prior_memos[:2]:
                lines.append(
                    f"- [{(m.get('created_at') or '?')[:10]}] '{(m.get('title') or '')[:100]}': "
                    f"{(m.get('executive_summary') or '')[:200]}"
                )
            continuity_block = (
                "\n=== PRIOR VIEWS ===\n"
                + "\n".join(lines)
                + "\nReconcile with prior view. If thesis changed, say so. If unchanged, note continuity.\n"
            )

        user_prompt = (
            f"Query: {plan.get('query', '')}\n"
            f"Intent: {plan.get('intent', '')} | Tickers: {', '.join(plan.get('tickers', []))} | Themes: {', '.join(plan.get('themes', []))}\n"
            f"{plan_shape_block}"
            f"{macro_block}"
            f"=== RESEARCH ===\n{data_summary}\n"
            f"{sub_q_block}\n"
            f"=== RISK ===\nRegime: {risk.get('macro_regime', '?')} | Level: {risk.get('overall_risk_level', '?')}\n"
            f"{risk.get('risk_narrative', '')}\n{risk_lines}\n"
            f"{falsification_block}\n"
            f"=== TRADE IDEAS ===\nPositioning: {strategy.get('portfolio_positioning', 'neutral')}\n"
            f"{trade_lines}\n\nHedges:\n{hedge_lines}\n"
            f"{calibration_block}"
            f"{continuity_block}\n"
            f"Produce the final intelligence memo as JSON. Open paragraph 1 with the macro backdrop. "
            f"Cite Q1/Q2/... by name in subsequent paragraphs. Include a paragraph on 'what would change "
            f"our view' citing the falsification criteria. Include the trade ideas as structured objects."
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
