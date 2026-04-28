"""
Portfolio Strategist — translates research + risk assessment into actionable trade ideas.

Has 2 price tools for entry/stop/target precision. Otherwise reasons over
the accumulated context from Research Analyst and Risk Manager.

Includes a server-side post-validation step (`validate_and_fix_trade_ideas`)
that scans every trade idea's entry/stop/target against the live price for
that ticker. If the LLM emitted prices that are >10% off, the entries get
clamped to a sensible band around live price and a `_price_corrected` flag
is added so the UI can show the user the system overrode the LLM.
"""

import logging
import re
from langchain_core.tools import tool

from agents.base_agent import BaseAgent
from data.market_client import MarketDataClient

logger = logging.getLogger(__name__)

_market = MarketDataClient()


def _parse_entry_zone(raw: str | None) -> tuple[float | None, float | None]:
    """
    Parse strings like '$255-260', '$255 - $260', '255.50', '$1,420-1,440'.
    Returns (lo, hi). Either may be None if unparseable.
    """
    if not raw:
        return None, None
    nums = re.findall(r"-?\d+(?:,\d{3})*(?:\.\d+)?", str(raw))
    parsed: list[float] = []
    for n in nums:
        try:
            parsed.append(float(n.replace(",", "")))
        except ValueError:
            continue
    if not parsed:
        return None, None
    if len(parsed) == 1:
        return parsed[0], parsed[0]
    return min(parsed[:2]), max(parsed[:2])


def assess_diversity(trade_ideas: list[dict]) -> dict:
    """
    Assess structural diversity of the Strategist's output. Returns:
        {monolithic: bool, reason: str, direction_split: {...}, sector_concentration: float}

    A monolithic output (all longs OR >80% same sector) is an anti-pattern
    for any 'risk-adjusted' / 'pair_trade' / 'hedging' query — orchestrator
    flags it so the user sees the system caught the issue.
    """
    if not trade_ideas:
        return {"monolithic": False, "reason": "no_ideas"}

    directions = [(t or {}).get("direction", "") for t in trade_ideas]
    long_count = sum(1 for d in directions if "bullish" in d)
    short_count = sum(1 for d in directions if "bearish" in d)
    neutral_count = sum(1 for d in directions if d == "neutral")

    sectors = [(t or {}).get("sector") or "Unknown" for t in trade_ideas]
    if sectors:
        from collections import Counter
        top_sector, top_count = Counter(sectors).most_common(1)[0]
        sector_share = top_count / len(sectors)
    else:
        top_sector = "Unknown"
        sector_share = 0.0

    monolithic_reasons = []
    if len(trade_ideas) >= 4 and long_count == len(trade_ideas):
        monolithic_reasons.append("all-long structure (no shorts, pairs, or hedges)")
    if len(trade_ideas) >= 4 and sector_share > 0.8:
        monolithic_reasons.append(f"sector concentration {int(sector_share*100)}% in {top_sector}")

    return {
        "monolithic": bool(monolithic_reasons),
        "reason": "; ".join(monolithic_reasons) if monolithic_reasons else "diverse",
        "direction_split": {"long": long_count, "short": short_count, "neutral": neutral_count},
        "sector_concentration_pct": round(sector_share * 100, 1),
        "top_sector": top_sector,
    }


def validate_and_fix_trade_ideas(
    trade_ideas: list[dict],
    live_prices: dict[str, float],
    max_drift_pct: float = 10.0,
    band_pct: float = 2.5,
) -> list[dict]:
    """
    Post-validate every trade idea against the live price for its ticker.

    For each idea:
      1. Drop the idea entirely if no live price is available.
      2. If entry_zone midpoint is within `max_drift_pct` of live price, leave it.
      3. Otherwise overwrite entry_zone with live ± band_pct, and rebuild
         stop/target preserving the original risk_reward_ratio if available.
      4. Always set `_price_corrected: true` and `_live_price_used: <px>` when
         we modified anything, so the UI can show a small badge.
    """
    if not trade_ideas:
        return []

    fixed: list[dict] = []
    for idea in trade_ideas:
        if not isinstance(idea, dict):
            continue
        tk = (idea.get("ticker") or "").upper().strip()
        if not tk:
            continue

        live = live_prices.get(tk)
        if not live or live <= 0:
            # No live price — drop the idea so the user never sees an
            # entry built on guessed numbers.
            logger.warning(
                "validator: dropping %s trade idea — no live price available",
                tk,
            )
            continue

        entry_lo, entry_hi = _parse_entry_zone(idea.get("entry_zone"))
        midpoint = (entry_lo + entry_hi) / 2.0 if entry_lo is not None and entry_hi is not None else None

        drift_ok = (
            midpoint is not None
            and live > 0
            and abs(midpoint - live) / live <= max_drift_pct / 100.0
        )

        if drift_ok:
            fixed.append(idea)
            continue

        # Entry too far from reality — rebuild around live price.
        direction = (idea.get("direction") or "").lower()
        is_long = "bullish" in direction
        is_short = "bearish" in direction

        band = live * band_pct / 100.0
        new_lo = round(live - band, 2)
        new_hi = round(live + band, 2)

        # Preserve risk_reward if the LLM gave one; otherwise default to 2:1.
        rr = idea.get("risk_reward_ratio")
        try:
            rr = float(rr) if rr is not None else 2.0
        except (TypeError, ValueError):
            rr = 2.0
        if rr <= 0:
            rr = 2.0

        # Choose stop and target on the correct side of live price.
        # Use a 4% stop distance as default — same scale as a typical swing trade.
        stop_distance = live * 0.04
        target_distance = stop_distance * rr

        if is_long:
            new_stop = round(live - stop_distance, 2)
            new_target = round(live + target_distance, 2)
        elif is_short:
            new_stop = round(live + stop_distance, 2)
            new_target = round(live - target_distance, 2)
        else:
            # Neutral — symmetric band, take_profit = upside, stop_loss = downside
            new_stop = round(live - stop_distance, 2)
            new_target = round(live + stop_distance, 2)

        idea = dict(idea)  # don't mutate caller's dict in place
        original_entry = idea.get("entry_zone")
        idea["entry_zone"] = f"${new_lo}-{new_hi}"
        idea["stop_loss"] = new_stop
        idea["take_profit"] = new_target
        idea["price_corrected"] = True
        idea["live_price_used"] = round(live, 2)
        idea["original_entry_zone"] = original_entry
        logger.info(
            "validator: corrected %s entry from %s to $%.2f-%.2f (live=$%.2f)",
            tk, original_entry, new_lo, new_hi, live,
        )
        fixed.append(idea)

    return fixed


@tool
def get_current_price(ticker: str) -> dict:
    """Get current price, 52-week range, and beta for precise entry/stop/target levels."""
    data = _market.get_fundamentals(ticker)
    return {
        "current_price": data.get("current_price"),
        "52w_high": data.get("52w_high"),
        "52w_low": data.get("52w_low"),
        "beta": data.get("beta"),
    }


@tool
def get_recent_prices(ticker: str) -> list:
    """Get 1-month price history for support/resistance identification."""
    return _market.get_price_history(ticker, period="1mo")


SYSTEM_PROMPT = """You are a senior portfolio manager at a quantitative hedge fund. You translate
research analysis and risk assessments into specific, actionable trade ideas.

PRICING DISCIPLINE — READ FIRST. The "LIVE PRICES" block in the user prompt
contains tool-fetched current prices. You MUST anchor every entry/stop/target
to those exact numbers. Do NOT invent prices. Do NOT pull prices from the
research summary's prose. Do NOT generate a trade idea for a ticker absent
from LIVE PRICES — use get_current_price first if you need one not listed.

Anchoring rules (the gate will reject violations and the response will be
post-validated against current price):
  - LONG ideas:  entry_zone brackets live_price ± 5%; stop_loss < live_price; take_profit > live_price
  - SHORT ideas: entry_zone brackets live_price ± 5%; stop_loss > live_price; take_profit < live_price
  - NEUTRAL ideas: entry_zone brackets live_price ± 3%; stop and target are symmetric
  - Quote the live price in your thesis (e.g., "at $426.55 spot, ...") so the
    reader can verify alignment.

Given the analysis plan, research data, and risk assessment, produce:

1. TRADE IDEAS: Ranked by conviction (best first). Each must have:
   - ticker: the stock symbol (MUST appear in LIVE PRICES block, or you must
     have called get_current_price on it within this run)
   - direction: strong_bullish | bullish | neutral | bearish | strong_bearish
   - conviction: 0-100 (only include ideas with conviction >= 50)
   - thesis: 1-3 sentence investment thesis (must quote live price)
   - entry_zone: range bracketing live price within ±5%
   - stop_loss: technical invalidation level on the correct side of live price
   - take_profit: target price on the correct side of live price
   - risk_reward_ratio: must be > 1.5:1 for inclusion
   - position_size_pct: % of portfolio (max 5%, adjusted for risk level)
   - time_horizon: intraday | days | weeks | months
   - catalysts: upcoming events that support the thesis
   - risks: specific risks to THIS trade

2. PORTFOLIO POSITIONING: Overall stance
   - risk_on: favoring equities, credit, growth
   - risk_off: favoring treasuries, cash, defensives
   - neutral: balanced
   - rotational: sector rotation theme

3. HEDGING RECOMMENDATIONS: Specific hedges
   - If long equities: put spreads, VIX calls, short correlated names
   - If concentrated: pair trades
   - Always include at least one hedge suggestion

Position sizing rules:
- Maximum single position: 5% of portfolio
- Adjust for risk_level from Risk Manager:
  low → full size, moderate → 75%, elevated → 50%, high → 25%, extreme → 0%
- Higher conviction = larger position
- Counter-trend trades require 2x evidence

Always produce exactly 5 trade ideas across different tickers and sectors to give the
CIO a diversified set of options. Include both long and short ideas when the environment
warrants it. Rank by conviction — best idea first.

For each trade idea:
- thesis: MUST be 2-3 sentences explaining WHY this trade, not just WHAT. Include a specific
  catalyst or data point that drives conviction. Bad: "AAPL looks good". Good: "AAPL's 15.7%
  revenue growth and $106B FCF provide downside protection at 32x P/E, with the $599 MacBook
  Neo launch in Q3 as a near-term catalyst for services revenue acceleration."
- catalysts: 3+ specific, dated events (earnings dates, product launches, FOMC meetings)
- risks: 3+ specific risks with quantified impact where possible

Always produce exactly 5 hedging recommendations. Each hedge should be a specific,
actionable instruction with the instrument, strike/level, rationale, and approximate
cost or premium. Examples:
  - "Buy SPY May 520 puts ($4.20 premium) to hedge portfolio beta — protects against 5% drawdown"
  - "Sell AAPL May 270 covered calls to reduce net delta and generate $3.50 income"
  - "Long VIX June 30 calls ($1.80) as tail risk insurance — pays off if VIX spikes above 35"
  - "Short XLE via May 85 puts as energy sector pair trade against long GOLD position"
  - "Buy TLT calls as duration hedge — benefits from flight-to-quality if equity sell-off accelerates"

Respond with JSON:
{{
    "trade_ideas": [
        {{
            "ticker": "AAPL",
            "direction": "bullish",
            "conviction": 75,
            "thesis": "...",
            "entry_zone": "$255-260",
            "stop_loss": 245.0,
            "take_profit": 285.0,
            "risk_reward_ratio": 2.5,
            "position_size_pct": 3.0,
            "time_horizon": "weeks",
            "catalysts": ["Q2 earnings July 25", "WWDC announcements"],
            "risks": ["China trade tensions", "Macro slowdown"]
        }}
    ],
    # Existing portfolio context will be injected into your prompt under
    # "EXISTING PORTFOLIO" — use it. Don't recommend trades that duplicate
    # exposure already on the book or breach the 30% sector cap.
    "portfolio_positioning": "risk_on | risk_off | neutral | rotational",
    # Hedge palette — DIVERSIFY across asset classes. A vanilla "SPY puts +
    # VIX calls" combo is correlated to itself. Pick from at least 3 of:
    #   - Equity index puts/spreads (SPY, QQQ, IWM)
    #   - Vol products (VIX calls, VXX, UVXY)
    #   - Rates/duration (TLT, IEF, TLT puts if expecting rate spike)
    #   - Credit (HYG/JNK shorts, IG-vs-HY pairs)
    #   - FX (DXY long via UUP if dollar haven, EUO/YCS for asymmetric bets)
    #   - Sector pair trades (XLF/XLU, XLY/XLP for cyclicals vs defensives)
    #   - Single-name hedges (short specific issuer with high beta to thesis)
    "hedging_recommendations": [
        "Buy SPY May 520 puts ($4.20) — portfolio beta hedge, protects against 5% drawdown",
        "Long VIX June 30 calls ($1.80) — tail risk insurance if vol spikes",
        "Long TLT (duration) — flight-to-quality hedge if equities crack",
        "Short HYG / long LQD pair — credit-stress hedge",
        "Long XLP / short XLY — defensive-vs-cyclical pair",
    ],
    "strategy_narrative": "<1-2 paragraph strategy explanation>"
}}"""

OUTPUT_INSTRUCTIONS = """TOOL BUDGET: Up to 8 tool calls. Allocate as follows:
  - The LIVE PRICES block already gives you tool-fetched prices for every
    plan ticker. Do NOT re-fetch those.
  - For any ticker you want to write an idea on that is NOT in LIVE PRICES,
    call get_current_price ONCE to get its price.
  - get_recent_prices is for support/resistance only — call sparingly (1-2 max).
  - After you have prices for all 5 ideas, STOP and emit the JSON.

Produce exactly 5 trade ideas and 5 hedging recommendations. Every entry/stop/
target MUST anchor to a tool-fetched price (LIVE PRICES or your own get_current_price
call) — no exceptions."""


class PortfolioStrategist(BaseAgent):
    agent_name = "portfolio_strategist"
    system_prompt = SYSTEM_PROMPT
    output_instructions = OUTPUT_INSTRUCTIONS
    # Bumped from default 6: with up to 5 trade ideas needing live prices,
    # plus the prompt's instruction to call get_current_price for any ticker
    # not in the LIVE PRICES block, the Strategist needs more headroom.
    max_iterations = 10

    def get_tools(self):
        return [get_current_price, get_recent_prices]

    def build_input_prompt(self, context: dict) -> str:
        plan = context.get("plan", {})
        research = context.get("research", {})
        risk = context.get("risk", {})
        portfolio = context.get("portfolio") or {}
        scorecard = context.get("scorecard") or {}
        live_prices: dict[str, float] = context.get("live_prices") or {}
        macro = context.get("macro_context") or {}

        summary = research.get("data_summary", "No research data.")
        if len(summary) > 2000:
            summary = summary[:2000] + "..."
        risk_narrative = risk.get("risk_narrative", "")
        if len(risk_narrative) > 500:
            risk_narrative = risk_narrative[:500] + "..."

        # Structured ticker_data — fundamentals + sentiment + options keyed by
        # ticker. Strategist uses these to set entry/stop/target precisely
        # (current price, options-implied move, IV) instead of guessing.
        ticker_data = research.get("ticker_data") or {}
        ticker_block = ""
        if ticker_data:
            tlines = []
            for tk, td in list(ticker_data.items())[:6]:
                if not isinstance(td, dict):
                    continue
                fund = td.get("fundamentals") or {}
                opt = td.get("options") or {}
                price = fund.get("current_price")
                pe = fund.get("pe_ratio")
                hi52 = fund.get("52w_high")
                lo52 = fund.get("52w_low")
                im = opt.get("implied_move_pct")
                iv = opt.get("atm_iv")
                tlines.append(
                    f"  {tk}: price={price} P/E={pe} 52w=[{lo52},{hi52}] "
                    f"impl_move={im}% atm_iv={iv}"
                )
            if tlines:
                ticker_block = "\n=== STRUCTURED TICKER DATA ===\n" + "\n".join(tlines) + "\n"

        # Live-price authority block — these prices are guaranteed fresh
        # from this exact run. The Strategist MUST anchor entry zones to
        # them. Listed separately and prominently so it can't be missed.
        prices_block = ""
        if live_prices:
            price_lines = "\n".join(
                f"  {tk}: ${px:.2f}"
                for tk, px in sorted(live_prices.items())
                if px and px > 0
            )
            if price_lines:
                prices_block = (
                    "\n=== LIVE PRICES (use these — do not invent) ===\n"
                    + price_lines
                    + "\n"
                    + "RULES (non-negotiable):\n"
                    + "  1. Every trade idea's entry_zone MUST bracket the live price within ±5%.\n"
                    + "  2. For LONG: stop_loss < live_price < take_profit. For SHORT: stop_loss > live_price > take_profit.\n"
                    + "  3. If a ticker isn't in this list, do NOT generate an idea for it.\n"
                    + "  4. Quote the live price you used in the thesis (e.g. 'at $426.55 spot').\n"
                )

        # Existing portfolio context — Strategist must size new ideas
        # against current book (not in a vacuum). Sector and net-exposure
        # awareness come straight from open trades.
        portfolio_block = ""
        positions = portfolio.get("open_positions") or []
        if positions:
            lines = []
            sector_totals: dict[str, float] = {}
            net_long = 0.0
            for p in positions[:15]:
                tk = p.get("ticker", "?")
                d = p.get("direction", "?")
                sz = float(p.get("size_pct") or 0)
                sec = p.get("sector") or "Unknown"
                sector_totals[sec] = sector_totals.get(sec, 0.0) + sz
                signed = sz if "bullish" in d else -sz
                net_long += signed
                lines.append(f"  - {tk} {d} {sz:.2f}% (sector: {sec})")
            sector_summary = ", ".join(
                f"{s}: {v:.1f}%" for s, v in sorted(sector_totals.items(), key=lambda kv: -kv[1])[:6]
            )
            portfolio_block = (
                f"\n=== EXISTING PORTFOLIO ({len(positions)} positions, "
                f"net long: {net_long:+.1f}%) ===\n"
                + "\n".join(lines)
                + f"\nSector exposure: {sector_summary}\n"
                + "Constraints: do not duplicate exposure already on the book; "
                + "factor in sector caps (30%) and net-long balance when sizing.\n"
            )

        # Calibration block: compact track-record signal. Uses bucket data
        # to indicate which conviction levels are safe.
        calibration_block = ""
        if scorecard and scorecard.get("signals", 0) >= 10:
            signals_n = int(scorecard.get("signals") or 0)
            hr_5d = scorecard.get("hit_rate_5d")
            ic_5d = scorecard.get("ic_5d")
            buckets = scorecard.get("by_conviction") or {}
            parts = []
            for k in ("very_high", "high", "medium", "low"):
                s = buckets.get(k)
                if isinstance(s, dict) and s.get("count"):
                    parts.append(f"{k}={s.get('hit_rate_5d')}%")
            calibration_block = (
                f"\n=== TRACK RECORD (n={signals_n}) ===\n"
                f"hit5d={hr_5d}% | IC5d={ic_5d}"
                + (f" | by conviction: {', '.join(parts)}" if parts else "")
                + "\nDampen conviction in buckets <50%, reinforce in buckets >55%.\n"
            )

        # Plan-shape directives — what the Interpreter explicitly asked for.
        # These steer the Strategist away from "5 carbon-copy longs" defaults.
        archetype = plan.get("idea_archetype") or []
        instrument = plan.get("instrument_preference") or "stock"
        benchmark = plan.get("benchmark") or ""
        comparison_set = plan.get("comparison_set") or []
        regime_sensitivity = plan.get("regime_sensitivity") or []

        archetype_block = ""
        if archetype:
            archetype_block = (
                "\n=== IDEA ARCHETYPE (structural diversity directive) ===\n"
                + "\n".join(f"  - {a}" for a in archetype)
                + "\nProduce IDEAS that match this structure. The Interpreter has determined "
                "the ideal mix of longs/shorts/pairs/hedges; do not collapse to all-long.\n"
            )

        instrument_block = (
            f"\n=== INSTRUMENT PREFERENCE: {instrument} ===\n"
            + {
                "stock": "Outright equity positions are appropriate.",
                "options": "Prefer options structures (calls / puts / spreads) for convex payoffs. Cite strike + expiry.",
                "pair_trade": "At least 2 of 5 ideas should be pair trades (long X / short Y). Cite both legs.",
                "spread": "Use multi-leg structures (call spreads, put spreads, calendars). Cite both legs.",
                "hedge": "All ideas are protective. Use puts, vol calls, defensive rotations, cross-asset hedges.",
                "mixed": "Mix outright + options + pair + hedge per idea_archetype directive.",
            }.get(instrument, "Outright equity positions.")
            + "\n"
        )

        benchmark_block = ""
        if benchmark:
            benchmark_block = (
                f"\n=== BENCHMARK: {benchmark} ===\n"
                f"Frame each thesis as 'should outperform {benchmark} by X% over {plan.get('time_horizon','weeks')}'. "
                f"Cite this in the thesis text.\n"
            )

        comparison_block_strat = ""
        if comparison_set:
            comparison_block_strat = (
                f"\n=== COMPARISON SET (valuation yardstick — DO NOT trade these) ===\n"
                f"  {', '.join(comparison_set)}\n"
                "Use these for relative valuation framing in your thesis. NEVER write a "
                "trade idea on a ticker from this list.\n"
            )

        regime_block = ""
        if regime_sensitivity:
            current_regime = (macro or {}).get("current_regime", "unknown")
            lines = []
            for rs in regime_sensitivity[:4]:
                if not isinstance(rs, dict):
                    continue
                marker = "★" if rs.get("regime") == current_regime else " "
                lines.append(
                    f"  {marker} {rs.get('regime')}: {rs.get('ideal_position', '?')} "
                    f"(conv ×{rs.get('conviction_multiplier', 1.0)}; assumes {rs.get('key_assumption', '?')})"
                )
            regime_block = (
                f"\n=== REGIME SENSITIVITY (★ = current regime: {current_regime}) ===\n"
                + "\n".join(lines)
                + "\nSize and structure for the CURRENT regime. Apply the conviction multiplier "
                "to your conviction scores.\n"
            )

        # Macro backdrop summary — beta context for systematic exposure
        macro_block_strat = ""
        if macro:
            parts = []
            if macro.get("current_regime"):
                parts.append(f"regime={macro['current_regime']}")
            if macro.get("vix") is not None:
                parts.append(f"VIX={macro['vix']}")
            if macro.get("credit_spreads") is not None:
                parts.append(f"HY={macro['credit_spreads']}")
            if macro.get("yield_curve") is not None:
                parts.append(f"YC={macro['yield_curve']}")
            if parts:
                macro_block_strat = "\n=== MACRO BACKDROP ===\n  " + " · ".join(parts) + "\n"

        return (
            f"Query: {plan.get('query', '')} | Tickers: {', '.join(plan.get('tickers', []))} | Horizon: {plan.get('time_horizon', 'weeks')}\n"
            f"Question type: {plan.get('question_type', 'alpha_finding')}\n"
            f"Regime: {risk.get('macro_regime', '?')} | Risk: {risk.get('overall_risk_level', '?')}\n"
            f"{macro_block_strat}"
            f"Research:\n{summary}\n"
            f"{ticker_block}"
            f"{prices_block}\n"
            f"Risk:\n{risk_narrative}\n"
            f"{portfolio_block}"
            f"{archetype_block}"
            f"{instrument_block}"
            f"{benchmark_block}"
            f"{comparison_block_strat}"
            f"{regime_block}"
            f"{calibration_block}\n"
            f"Produce 5 trade ideas and portfolio strategy JSON. Anchor every entry/stop/target to the LIVE PRICES block above. "
            f"You may call get_current_price for additional tickers not in the LIVE PRICES block, but do NOT override prices already given. "
            f"For each trade idea, include 'beta_to_spy' (estimated from research/known beta), 'sector', "
            f"and 'regime_conditional_size_pct' (size at current regime per regime_sensitivity multiplier)."
        )
