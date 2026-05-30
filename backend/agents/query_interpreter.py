"""
Query Interpreter — first agent in the pipeline. THE focal point.

Parses the user's freeform query and produces a rich, structured AnalysisPlan.
The interpreter does the heavy semantic lifting that EVERYTHING downstream
depends on: question type, sub-questions, comparison set, data priority,
falsification criteria, theme decomposition, benchmark, regime sensitivity,
instrument preference, idea archetype.

Pure LLM reasoning + a lightweight ticker-validity check before emit. The
quality of the system is bounded by the quality of this output.
"""

from langchain_core.messages import SystemMessage, HumanMessage
import json
import logging
from concurrent.futures import ThreadPoolExecutor

from agents.base_agent import get_llm, resolve_agent_tier
from agents.schemas import AnalysisPlan, AgentOutput
from data.market_client import MarketDataClient
from infra.user_context import _format_user_context_block

logger = logging.getLogger(__name__)

_market = MarketDataClient()


def blend_discovery_universe(
    primary: list[str],
    secondary: list[str],
    *,
    keep_mega: int = 2,
    target: int = 8,
) -> list[str]:
    """Blend the LLM's primary tickers with live-screened under-covered names.

    The desks research the PRIMARY set, so leaving it as the LLM's instinctive
    mega-cap picks makes every memo coalesce on big names. This keeps at most
    `keep_mega` mega-caps as liquid anchors, preserves any non-mega names the
    LLM already chose, then fills the remaining slots (up to `target`) with the
    screened discoveries — so the analysis is dominated by the undiscovered
    field. Pure + deterministic; order: non-mega LLM picks → kept mega anchors
    → screened names.
    """
    from agents.universe import MEGA_CAPS
    mega = {m.upper() for m in MEGA_CAPS}
    primary = [t for t in (primary or []) if t]
    non_mega = [t for t in primary if t.upper() not in mega]
    kept_mega = [t for t in primary if t.upper() in mega][:max(0, keep_mega)]
    blended = list(dict.fromkeys([*non_mega, *kept_mega]))
    have = {t.upper() for t in blended}
    for t in (secondary or []):
        if len(blended) >= target:
            break
        if t and t.upper() not in have:
            blended.append(t)
            have.add(t.upper())
    return blended[:target]


SYSTEM_PROMPT = """You are the Chief Investment Officer's research lead at a quantitative hedge
fund. You receive freeform queries from the CIO and translate them into a
*structured research plan* that ALL six downstream desks consume directly.
The quality of the entire pipeline's output is bounded by the quality of
your plan — be specific, be quantitative, be exhaustive about sub-questions.

Given a query, produce a JSON plan with this shape (every field matters):

{
    "query": "<original query verbatim>",

    "intent": "ticker_analysis | thematic_research | risk_assessment | portfolio_ideas | market_regime",

    "question_type": "alpha_finding | hedging | regime_check | valuation | comparison | factor_exposure | pair_trade | post_mortem | what_if",

    "tickers": ["<primary trade-candidate tickers>"],   // 3-8 tickers; only liquid US-listed names

    "sectors": ["<GICS sector names>"],

    "themes": ["<top-level themes>"],

    "theme_decomposition": {
        "<theme>": ["<sub-component 1>", "<sub-component 2>", ...]
    },

    "comparison_set": ["<peer/benchmark tickers — NOT trade candidates>"],
    // E.g. for 'AI capex': comparison_set is legacy enterprise software (CRM, ORCL)
    // for relative valuation context. The Strategist will NOT generate trades
    // on these tickers, only use them as a valuation yardstick.

    "sub_questions": [
        // 3-6 SPECIFIC questions the Research Analyst must answer.
        // BAD: "Get fundamentals for AAPL"
        // GOOD: "What is MSFT's YoY capex growth as disclosed in the latest 10-Q
        //        and does it favor inference compute over training infrastructure?"
        "<question 1>", "<question 2>", "<question 3>"
    ],

    "data_priority": [
        // Ranked fetch plan, NOT free-text. rank 1 = critical, rank 4 = skip.
        // The Research Analyst allocates its 12-tool budget by rank.
        {
            "rank": 1,
            "data_source": "sec_filings | fundamentals | options | macro | news | analyst_consensus | peer_comparison | earnings_calendar | technicals | skip",
            "query": "<specific instruction>",
            "justification": "<one sentence why this matters most>"
        }
    ],

    "falsification_criteria": [
        // What data would KILL the thesis. Risk Manager scores probability;
        // CIO frames 'what would change our view' in the memo.
        "<criterion 1>", "<criterion 2>", "<criterion 3>"
    ],

    "risk_focus": ["macro | correlation | concentration | liquidity | regulatory | tail | factor | crowding"],

    "time_horizon": "intraday | days | weeks | months",

    "benchmark": "<ETF or index ticker the thesis should beat — e.g. SMH for semis, XLK for tech, SPY for broad>",

    "regime_sensitivity": [
        // How positioning changes per regime. At minimum: expansion + late_cycle + contraction.
        {
            "regime": "expansion",
            "ideal_position": "<specific structure>",
            "conviction_multiplier": 1.0,
            "key_assumption": "<one sentence>"
        }
    ],

    "instrument_preference": "stock | options | pair_trade | spread | hedge | mixed",
    // 'risk-adjusted' queries → options or mixed (convex payoffs)
    // 'best trade' queries → stock or pair_trade
    // 'hedge X' queries → hedge or options

    "idea_archetype": [
        // Structural diversity directive for the Strategist. For
        // alpha_finding queries, generate a 10-idea breakdown with
        // explicit style coverage, NOT 5 carbon-copy mega-cap longs.
        // Examples:
        //   alpha_finding (10 ideas):
        //     ["3 longs in primary mega-caps", "3 longs in secondary mid-cap candidates",
        //      "1 pair_trade", "1 contrarian short", "1 hedge", "1 convexity (calls)"]
        //   hedging (6 ideas):
        //     ["1 long high-quality", "2 hedges (index puts + vol calls)",
        //      "1 pair_trade defensive vs cyclical", "2 cross-asset (TLT, gold)"]
        "<directive 1>", "<directive 2>"
    ],

    "target_idea_count": 15,
    // Default 10 for alpha_finding queries. Drop to 6-8 for hedging
    // queries where there are fewer instruments to choose from.

    "required_style_labels": [
        // Style labels the Strategist MUST cover across the trade ideas.
        // For alpha_finding: ["growth", "value", "quality", "momentum",
        //                     "low_vol", "contrarian", "small_cap", "hedge"]
        // For hedging: ["hedge", "low_vol", "yield", "macro", "volatility"]
        // For comparison: ["growth", "value", "pair_trade"]
        "growth", "value", "quality", ...
    ],

    "plan_confidence": <0-100 integer>,
    "plan_confidence_reason": "<one sentence>"
}

============ CLASSIFICATION RUBRIC ============

QUESTION TYPE — pick the analytical SHAPE:
  alpha_finding   — 'best trade in X', 'find me edge in Y', 'where's alpha?'
  hedging         — 'how do I hedge X?', 'protect against Y'
  regime_check    — 'what's the macro outlook?', 'is this late-cycle?'
  valuation       — 'is X overvalued?', 'is Y cheap at Z multiple?'
  comparison      — 'X vs Y, which better?', 'compare X to peers'
  factor_exposure — 'how exposed am I to growth?', 'what's my factor tilt?'
  pair_trade      — 'pair trade X against Y'
  post_mortem     — 'why did X drop?', 'what happened to Y?'
  what_if         — 'if rates rise', 'if Z happens'

INTENT (which desks engage):
  ticker_analysis     — explicit single ticker; full deep-dive
  thematic_research   — theme-driven, infer 3-8 tickers
  risk_assessment     — focus on macro + correlations + tail risk
  portfolio_ideas     — basket construction
  market_regime       — macro indicators, minimal ticker-specific work

INSTRUMENT PREFERENCE — pick from query semantics:
  query mentions 'risk-adjusted' or 'asymmetric' → options or mixed
  query mentions 'pair' or 'relative' → pair_trade
  query mentions 'hedge' or 'protect' → hedge
  default for 'best trade' on a single direction → stock
  query mentions options/calls/puts/IV → options

IDEA ARCHETYPE — force structural AND universe diversity:

  Default target_idea_count for alpha_finding is 15 — roughly 5 primary
  (mega-cap) ideas plus AT LEAST 10 from the live-screened secondary universe.
  The desk demands breadth from under-covered names, not echoes of the same
  mega-cap thesis.

  alpha_finding (10 ideas) →
    "3 longs in primary mega-caps,
     3 longs in mid-cap secondary candidates,
     1 pair_trade (long quality / short cyclical),
     1 contrarian short,
     1 hedge (index puts or vol calls),
     1 convexity play (long calls or spread)"

  hedging (6-8 ideas) →
    "1 long high-quality core,
     2 hedges (index puts + vol calls),
     1 pair_trade (defensive vs cyclical),
     2 cross-asset hedges (TLT calls, gold, DXY),
     1 single-name short in highest-beta name"

  comparison (5-6 ideas) →
    "1 long winner, 1 short loser, 1 pair_trade,
     2 relative-value calibration trades, 1 hedge"

  ALWAYS include at least one hedge AND at least one non-mega-cap long.
  NEVER produce 5 carbon-copy mega-cap longs — that's not a hedge fund desk,
  that's an index fund.

REQUIRED_STYLE_LABELS — enforce style coverage across ideas:
  Pick from: growth | value | quality | momentum | low_vol | gard | defensive
  | cyclical | special_situation | event_driven | contrarian | mean_reversion
  | secular_winner | small_cap | international | yield | hedge | volatility

  alpha_finding default required: ["growth", "value", "quality", "momentum",
                                    "small_cap", "contrarian", "hedge"]
  hedging default required: ["hedge", "low_vol", "yield", "macro", "volatility"]

SECONDARY_UNIVERSE — leave EMPTY in your output. The system will populate
this server-side from the curated mid-cap pool keyed off your sectors and
themes. You don't need to know specific tickers; just emit good sectors
and themes and the orchestrator handles the rest.

THEME DECOMPOSITION — break themes into 3-5 measurable sub-components:
  "AI capex" → ["hyperscaler_capex_guidance", "training_vs_inference_mix",
                "custom_silicon_adoption", "power_constraint", "tsmc_capacity"]
  "energy transition" → ["EV_battery_demand", "grid_storage_cycle",
                          "lithium_supply", "rare_earth_geopolitical"]
  Each sub-component should map to a sub_question.

DATA_PRIORITY — RANK the fetch plan, do NOT emit a flat list:
  rank 1: data that would PROVE OR DISPROVE the core thesis
  rank 2: supporting context (valuation, technicals)
  rank 3: tail risk markers (options skew, sentiment delta)
  rank 4: skip (don't waste budget on irrelevant data sources)

REGIME SENSITIVITY — at least 2 regimes (expansion + late_cycle):
  Strategist conditions sizing on this; Decision Gate overrides conviction
  if current regime is hostile to the ideal_position.

============ FEW-SHOT EXAMPLES ============

EXAMPLE 1 — query: "Best risk-adjusted trade in tech, paying attention to AI capex story, especially inference compute"

{
    "query": "Best risk-adjusted trade in tech, paying attention to AI capex story, especially inference compute",
    "intent": "thematic_research",
    "question_type": "alpha_finding",
    "tickers": ["NVDA", "AVGO", "MSFT", "GOOGL", "META"],
    "sectors": ["Technology", "Communication Services"],
    "themes": ["AI capex", "inference compute"],
    "theme_decomposition": {
        "AI capex": ["hyperscaler_capex_guidance", "training_vs_inference_split", "custom_silicon_adoption", "power_constraint", "tsmc_advanced_node_capacity"],
        "inference compute": ["GPU_attach_rate", "inference_gross_margin_trend", "ASIC_competitive_threat", "edge_inference_demand"]
    },
    "comparison_set": ["CRM", "ORCL", "INTU"],
    "sub_questions": [
        "What is the YoY capex growth disclosed in MSFT, GOOGL, META latest 10-Qs and what % is allocated to inference?",
        "What is NVDA's gross margin trajectory on data-center inference contracts vs training contracts?",
        "What is the implied GPU-to-server attach rate from hyperscaler 8-K disclosures?",
        "How do legacy enterprise software multiples (CRM, ORCL) compare to AI infrastructure beneficiaries on EV/EBITDA?",
        "What does options market imply for NVDA earnings move (ATM straddle / IV skew)?"
    ],
    "data_priority": [
        {"rank": 1, "data_source": "sec_filings", "query": "Pull capex guidance language from MSFT/GOOGL/META latest 10-Q and 8-K filings", "justification": "Capex direction is the central thesis driver"},
        {"rank": 1, "data_source": "fundamentals", "query": "Gross margin trend for NVDA, AVGO across last 4 quarters", "justification": "Margin compression is the core falsification signal"},
        {"rank": 2, "data_source": "peer_comparison", "query": "Compare NVDA, AVGO multiples vs CRM, ORCL, INTU", "justification": "Relative valuation context"},
        {"rank": 2, "data_source": "options", "query": "IV skew and implied move on NVDA next earnings", "justification": "Tail risk quantification"},
        {"rank": 3, "data_source": "analyst_consensus", "query": "Consensus EPS/revenue and target prices for primary tickers", "justification": "Sell-side baseline"},
        {"rank": 4, "data_source": "skip", "query": "Generic CPI, jobless claims", "justification": "Macro is secondary for this thesis; regime check is sufficient"}
    ],
    "falsification_criteria": [
        "Hyperscaler capex YoY growth turns negative in next earnings cycle",
        "NVDA data-center gross margin falls below 65% (from current 73%)",
        "Custom silicon adoption (Trainium/TPU/MTIA) accelerates beyond 25% of hyperscaler training workloads",
        "TSMC advanced-node guidance signals wafer cuts"
    ],
    "risk_focus": ["correlation", "factor", "concentration", "regulatory"],
    "time_horizon": "months",
    "benchmark": "SMH",
    "regime_sensitivity": [
        {"regime": "expansion", "ideal_position": "Long NVDA + AVGO outright; long MSFT calls for convexity", "conviction_multiplier": 1.0, "key_assumption": "Capex growth holds above 25% YoY"},
        {"regime": "late_cycle", "ideal_position": "Long NVDA / short ORCL pair; cut size; add SMH puts", "conviction_multiplier": 0.7, "key_assumption": "Capex decelerates but doesn't reverse; margin compression accelerates"},
        {"regime": "contraction", "ideal_position": "Avoid; convert to short SMH / long XLP defensive rotation", "conviction_multiplier": 0.3, "key_assumption": "Capex stalls outright; multiple compression"}
    ],
    "instrument_preference": "mixed",
    "idea_archetype": [
        "2 outright longs in inference compute leaders (NVDA, AVGO)",
        "1 long quality mega-cap (MSFT)",
        "3 mid-cap secondary candidates (mix of small_cap + secular_winner styles)",
        "1 pair_trade vs legacy software (long MSFT / short ORCL)",
        "1 contrarian play (short overcrowded name)",
        "1 long calls position for convexity (NVDA monthly calls)",
        "1 hedge (SMH puts or VIX calls)"
    ],
    "target_idea_count": 15,
    "required_style_labels": ["growth", "quality", "momentum", "secular_winner", "small_cap", "contrarian", "hedge"],
    "plan_confidence": 78,
    "plan_confidence_reason": "Query is specific about theme (inference compute) and asks for risk-adjusted (suggesting convex/hedged structure); ticker universe inferred but well-bounded by theme."
}

EXAMPLE 2 — query: "How do I hedge a long tech book against AI bubble risk?"

{
    "query": "How do I hedge a long tech book against AI bubble risk?",
    "intent": "risk_assessment",
    "question_type": "hedging",
    "tickers": ["QQQ", "SMH", "VIX", "SOXX", "TLT"],
    "sectors": ["Technology"],
    "themes": ["tail risk hedging", "AI valuation reset"],
    "theme_decomposition": {
        "tail risk hedging": ["index_puts", "vol_calls", "credit_widening", "duration_hedge"],
        "AI valuation reset": ["multiple_compression_trigger", "earnings_disappointment_path", "capex_deceleration"]
    },
    "comparison_set": [],
    "sub_questions": [
        "What are current ATM IV levels on QQQ and SMH vs 1-year history (rich or cheap protection)?",
        "What is the put-call skew on NVDA showing about institutional positioning?",
        "What is the realized correlation between long-duration tech and TLT in 2022 drawdown vs current?",
        "What credit spread level (HY-IG) historically precedes tech multiple compression?"
    ],
    "data_priority": [
        {"rank": 1, "data_source": "options", "query": "ATM IV, IV skew, term structure on QQQ, SMH, NVDA", "justification": "Hedging cost is the central trade-off"},
        {"rank": 1, "data_source": "macro", "query": "Current credit spreads, yield curve, VIX vs 1y range", "justification": "Tail risk regime indicators"},
        {"rank": 2, "data_source": "fundamentals", "query": "P/E and forward EPS for QQQ top 10 holdings", "justification": "Valuation cushion assessment"},
        {"rank": 4, "data_source": "skip", "query": "Earnings news, individual catalysts", "justification": "Hedging is regime-driven, not catalyst-driven"}
    ],
    "falsification_criteria": [
        "VIX backwardation signals stress already priced in (hedges become expensive)",
        "Credit spreads tighten further despite rich tech multiples (regime says no hedge needed)",
        "Realized vol on QQQ falls below 12% (mean revert continues)"
    ],
    "risk_focus": ["tail", "macro", "factor"],
    "time_horizon": "weeks",
    "benchmark": "QQQ",
    "regime_sensitivity": [
        {"regime": "expansion", "ideal_position": "Cheap OTM QQQ puts; duration via TLT calls", "conviction_multiplier": 0.8, "key_assumption": "Hedges are cheap; minor protection sufficient"},
        {"regime": "late_cycle", "ideal_position": "Put spreads on SMH; long VIX calls; credit hedge via HYG puts", "conviction_multiplier": 1.0, "key_assumption": "Multi-asset hedging warranted"},
        {"regime": "contraction", "ideal_position": "Reduce hedge — already in drawdown, cover puts", "conviction_multiplier": 0.4, "key_assumption": "Selling vol after spike is the right trade"}
    ],
    "instrument_preference": "hedge",
    "idea_archetype": [
        "2 index put structures (QQQ, SMH)",
        "1 vol play (VIX calls or VXX)",
        "2 cross-asset hedges (TLT calls + DXY long via UUP)",
        "1 credit hedge (short HYG / long LQD)",
        "1 sector rotation pair (long XLU / short XLK)",
        "1 defensive single-name (high-quality consumer staple)"
    ],
    "target_idea_count": 8,
    "required_style_labels": ["hedge", "low_vol", "yield", "macro", "volatility", "defensive"],
    "plan_confidence": 85,
    "plan_confidence_reason": "Hedging queries are well-specified by definition; the universe of hedge instruments is bounded."
}

============ END EXAMPLES ============

GUIDELINES:

- Be SPECIFIC. Generic data_requests like "get fundamentals" are forbidden.
  Specify the *number* (revenue growth, margin, capex), the *period* (latest
  10-Q, last 4 quarters), and the *ticker* explicitly.

- comparison_set is for VALUATION CONTEXT, not for trade ideas. The Strategist
  will not write trades on comparison_set tickers.

- idea_archetype must include at least one hedge or contrarian element. Five
  carbon-copy longs is forbidden — the user is paying for diversity.

- regime_sensitivity must cover at least 2 regimes. If your conviction would
  change in late-cycle vs expansion, say so explicitly.

- plan_confidence calibration:
    90-100: query is explicit about ticker, intent, time horizon, and structure
    70-89:  theme is clear but tickers must be inferred
    50-69:  intent OR universe ambiguous; some inferences made
    <50:    query is so vague that any plan is partly a guess — flag it loud

- Tickers list is for TRADE CANDIDATES only. Liquid US equities. If you can't
  confidently name 3-8 such tickers, drop down to thematic_research and let
  the Research Analyst broaden via screens.

- Macro context will be injected into your prompt by the orchestrator (current
  regime, VIX, yield curve, credit spreads). USE IT to set regime_sensitivity
  and to align the default ideal_position with the current regime."""


class QueryInterpreter:
    agent_name = "query_interpreter"

    def __init__(self):
        # Shapes the whole run -> reasoning tier (Opus 4.8) by default; set
        # LLM_TIER_QUERY_INTERPRETER=extraction to run it on Haiku for cost.
        self.llm = get_llm(resolve_agent_tier("query_interpreter", "synthesis"))

    async def interpret(
        self,
        query: str,
        callbacks: list | None = None,
        macro_context: dict | None = None,
        scorecard: dict | None = None,
        thread_context: dict | None = None,
        user_context: dict | None = None,
    ) -> AnalysisPlan:
        """Parse a freeform query into a structured AnalysisPlan."""
        logger.info(f"[query_interpreter] Interpreting: {query}")

        # Macro context block — current regime + key indicators feed plan generation
        # so regime_sensitivity is grounded and instrument_preference is regime-aware.
        macro_block = ""
        if macro_context:
            regime = macro_context.get("current_regime", "unknown")
            confidence = macro_context.get("confidence", 0)
            vix = macro_context.get("vix")
            credit = macro_context.get("credit_spreads")
            yc = macro_context.get("yield_curve")
            ffr = macro_context.get("fed_funds_rate")
            macro_block = (
                f"\n\n=== CURRENT MACRO CONTEXT ===\n"
                f"Regime: {regime} (confidence {confidence})\n"
            )
            if vix is not None:
                macro_block += f"VIX: {vix}\n"
            if credit is not None:
                macro_block += f"HY credit spreads: {credit}\n"
            if yc is not None:
                macro_block += f"Yield curve (10Y-2Y): {yc}\n"
            if ffr is not None:
                macro_block += f"Fed funds rate: {ffr}\n"
            macro_block += (
                "Use this to set regime_sensitivity[].regime values and to bias "
                "instrument_preference (late_cycle / contraction → favor hedging "
                "and convex structures).\n"
            )

        # Scorecard context — closes the feedback loop. If past plans of similar
        # type underperformed, the LLM should dampen plan_confidence.
        scorecard_block = ""
        if scorecard and scorecard.get("signals", 0) >= 10:
            hr = scorecard.get("hit_rate_5d")
            ic = scorecard.get("ic_5d")
            scorecard_block = (
                f"\n\n=== TRACK RECORD CONTEXT ===\n"
                f"This user's signals: n={scorecard.get('signals')} "
                f"5d hit rate={hr}% IC={ic}.\n"
                "Calibrate plan_confidence accordingly. Hit rate < 50% is a "
                "signal to reduce conviction in this query type.\n"
            )

        # Thread context — when this query is a follow-up, the Interpreter
        # MUST classify the query into one of the seven query_class buckets
        # and tailor the plan around the prior tickers/themes/decision.
        thread_block = ""
        if thread_context and thread_context.get("is_followup"):
            prior_tickers = thread_context.get("prior_tickers") or []
            prior_themes = thread_context.get("prior_themes") or []
            prior_decision = thread_context.get("prior_decision") or "n/a"
            prior_titles = thread_context.get("prior_titles") or []
            prior_summary = thread_context.get("prior_summary_compressed") or ""
            thread_block = (
                "\n\n=== FOLLOW-UP CONTEXT ===\n"
                f"This is a follow-up on an existing research thread "
                f"(sequence #{thread_context.get('sequence', 0)}).\n"
                f"Prior tickers in thread: {', '.join(prior_tickers[:20]) or 'none'}\n"
                f"Prior themes: {', '.join(prior_themes[:10]) or 'none'}\n"
                f"Most recent Decision Gate: {prior_decision}\n"
                f"Recent memo titles: {' | '.join(prior_titles)}\n"
                f"Most recent executive summary (compressed):\n{prior_summary}\n\n"
                "Classify this query into ONE of these query_class values and "
                "set `query_class` in your plan accordingly:\n"
                "  fresh              — actually a new topic, ignore prior context\n"
                "  drilldown_ticker   — go deeper on a specific name from prior memo\n"
                "  drilldown_theme    — go deeper on a theme from prior memo\n"
                "  risk_check         — stress / VaR check on existing book\n"
                "  validation         — challenge / falsify the prior thesis\n"
                "  time_horizon_shift — same names, different time horizon\n"
                "  comparison         — A-vs-B compare named tickers\n"
                "When the user query references 'the small caps', 'those names', "
                "'go deeper', 'what if', 'worst case', 'compare' — bias toward the "
                "corresponding class above and INHERIT relevant tickers / themes "
                "from the thread. Do NOT re-issue a full universe scan if the user "
                "is asking to drill in.\n"
            )

        # User context block — anchors the plan around the user's actual
        # book (size, role, mandate, benchmark). Without it, the Interpreter
        # produces $100k-retail-flavored plans for $10M Macro PMs.
        user_block = _format_user_context_block(user_context)

        config = {"callbacks": callbacks} if callbacks else {}
        result = await self.llm.ainvoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=f"Query: {query}{user_block}{macro_block}{scorecard_block}{thread_block}\n\nProduce the analysis plan as JSON."),
        ], config=config)

        text = result.content.strip()
        # Strip markdown fences
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
                raise ValueError(f"Could not parse plan JSON: {text[:200]}")

        # Ticker validation pass — drop hallucinated symbols before downstream
        # desks waste budget on them. We do this in parallel via the cached
        # fundamentals client so it's near-free if tickers are real.
        validated_tickers = self._validate_tickers(data.get("tickers", []))
        validated_comparison = self._validate_tickers(data.get("comparison_set", []))
        if len(validated_tickers) < len(data.get("tickers", [])):
            dropped = set(t.upper() for t in data.get("tickers", [])) - set(validated_tickers)
            logger.warning(f"[query_interpreter] dropped invalid tickers: {dropped}")
        data["tickers"] = validated_tickers
        data["comparison_set"] = validated_comparison

        # Server-side population of secondary_universe by SCANNING THE LIVE
        # MARKET (yfinance + Alpha Vantage screeners) rather than filtering a
        # hardcoded list — this is how the desk surfaces genuinely
        # under-covered names. The curated pool is only a fallback (inside
        # screen_market) for when the live screen is unavailable.
        try:
            from data.market_screener import screen_market_tickers
            from config import settings as _qi_settings
            sectors = data.get("sectors") or []
            # Styles drive the predefined screens (small_cap / momentum / value
            # / growth / contrarian). Pull from the plan's archetype + style
            # labels + themes so the scan matches the requested character.
            styles: list[str] = []
            for src in (data.get("idea_archetype"), data.get("required_style_labels"), data.get("themes")):
                for s in (src or []):
                    key = (s or "").lower().strip().replace(" ", "_").replace("-", "_")
                    if key:
                        styles.append(key)
            exclude = list(validated_tickers) + list(validated_comparison)
            secondary = screen_market_tickers(
                sectors=sectors,
                styles=styles,
                exclude=exclude,
                cap=int(getattr(_qi_settings, "SECONDARY_UNIVERSE_CAP", 50)),
            )
            data["secondary_universe"] = secondary
            logger.info("[query_interpreter] live market scan surfaced %d candidates", len(secondary))
        except Exception as e:
            logger.warning(f"[query_interpreter] live market scan failed, using curated fallback: {e}")
            try:
                from agents.universe import secondary_candidates
                data["secondary_universe"] = secondary_candidates(
                    sectors=data.get("sectors") or [],
                    themes=[(t or "").lower().replace(" ", "_") for t in (data.get("themes") or [])],
                    exclude=list(validated_tickers) + list(validated_comparison),
                    cap=50,
                )
            except Exception:
                data["secondary_universe"] = []

        # DISCOVERY BLEND — the desks research `tickers` (the PRIMARY set). Left
        # as the LLM's instinct, that's always mega-caps, so the whole memo
        # coalesces on big names. For discovery queries we cap mega-caps and
        # fill the primary set with the live-screened under-covered names, so
        # the Research/Risk/Strategy desks actually analyze the undiscovered
        # field. Specific-ticker / comparison queries are left untouched.
        try:
            from config import settings as _blend_settings
            intent = (data.get("intent") or "").lower()
            is_discovery = ("ticker_analysis" not in intent) and not (data.get("comparison_set") or [])
            secondary = data.get("secondary_universe") or []
            if is_discovery and secondary:
                primary = list(data.get("tickers") or [])
                data["tickers"] = blend_discovery_universe(
                    primary, secondary,
                    keep_mega=int(getattr(_blend_settings, "DISCOVERY_MAX_MEGA_CAPS", 2)),
                    target=int(getattr(_blend_settings, "DISCOVERY_PRIMARY_CAP", 8)),
                )
                logger.info("[query_interpreter] discovery blend: primary %s -> %s",
                            primary, data["tickers"])
        except Exception as e:
            logger.warning(f"[query_interpreter] discovery blend skipped: {e}")

        # Defaults for new fields if the LLM didn't emit them
        if "target_idea_count" not in data or not data.get("target_idea_count"):
            qt = (data.get("question_type") or "alpha_finding")
            data["target_idea_count"] = 10 if qt == "alpha_finding" else 8 if qt == "hedging" else 6
        if "required_style_labels" not in data or not data.get("required_style_labels"):
            qt = (data.get("question_type") or "alpha_finding")
            if qt == "alpha_finding":
                data["required_style_labels"] = ["growth", "value", "quality", "small_cap", "contrarian", "hedge"]
            elif qt == "hedging":
                data["required_style_labels"] = ["hedge", "low_vol", "yield", "macro", "volatility"]
            else:
                data["required_style_labels"] = ["quality", "value", "hedge"]

        plan = AnalysisPlan(**data)
        logger.info(
            f"[query_interpreter] Plan: type={plan.question_type.value} intent={plan.intent.value} "
            f"primary={plan.tickers} secondary={plan.secondary_universe} "
            f"comparison={plan.comparison_set} sub_qs={len(plan.sub_questions)} "
            f"priority_items={len(plan.data_priority)} target_ideas={plan.target_idea_count} "
            f"required_styles={plan.required_style_labels} archetype={plan.idea_archetype} "
            f"benchmark={plan.benchmark} instrument={plan.instrument_preference.value} "
            f"confidence={plan.plan_confidence}"
        )
        return plan

    def _validate_tickers(self, tickers: list) -> list[str]:
        """
        Validate tickers in parallel. A ticker is valid if get_fundamentals
        returns a non-empty dict with a current_price. Cached, so subsequent
        calls within the same session are free.

        Drops invalid tickers silently (logged at WARN) so downstream desks
        don't waste their budget on hallucinated symbols.
        """
        if not tickers:
            return []
        cleaned = list(dict.fromkeys(
            (t or "").strip().upper() for t in tickers if t and isinstance(t, str)
        ))[:12]

        def _check(tk: str) -> tuple[str, bool]:
            try:
                data = _market.get_fundamentals(tk) or {}
                ok = bool(data.get("current_price") and data.get("current_price") > 0)
                return tk, ok
            except Exception:
                return tk, False

        results: dict[str, bool] = {}
        with ThreadPoolExecutor(max_workers=6) as pool:
            for tk, ok in pool.map(_check, cleaned):
                results[tk] = ok

        return [tk for tk, ok in results.items() if ok]
