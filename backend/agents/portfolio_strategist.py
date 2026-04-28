"""
Portfolio Strategist — translates research + risk assessment into actionable trade ideas.

Has 2 price tools for entry/stop/target precision. Otherwise reasons over
the accumulated context from Research Analyst and Risk Manager.
"""

from langchain_core.tools import tool

from agents.base_agent import BaseAgent
from data.market_client import MarketDataClient

_market = MarketDataClient()


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

Given the analysis plan, research data, and risk assessment, produce:

1. TRADE IDEAS: Ranked by conviction (best first). Each must have:
   - ticker: the stock symbol
   - direction: strong_bullish | bullish | neutral | bearish | strong_bearish
   - conviction: 0-100 (only include ideas with conviction >= 50)
   - thesis: 1-3 sentence investment thesis
   - entry_zone: specific price or range (e.g., "$255-260")
   - stop_loss: technical invalidation level
   - take_profit: target price
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

OUTPUT_INSTRUCTIONS = """CRITICAL: Call get_current_price for AT MOST 3 tickers, then IMMEDIATELY
produce your JSON response. Do NOT call get_recent_prices unless absolutely needed.
Produce exactly 5 trade ideas and 5 hedging recommendations."""


class PortfolioStrategist(BaseAgent):
    agent_name = "portfolio_strategist"
    system_prompt = SYSTEM_PROMPT
    output_instructions = OUTPUT_INSTRUCTIONS

    def get_tools(self):
        return [get_current_price, get_recent_prices]

    def build_input_prompt(self, context: dict) -> str:
        plan = context.get("plan", {})
        research = context.get("research", {})
        risk = context.get("risk", {})
        portfolio = context.get("portfolio") or {}
        scorecard = context.get("scorecard") or {}

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

        return (
            f"Query: {plan.get('query', '')} | Tickers: {', '.join(plan.get('tickers', []))} | Horizon: {plan.get('time_horizon', 'weeks')}\n"
            f"Regime: {risk.get('macro_regime', '?')} | Risk: {risk.get('overall_risk_level', '?')}\n\n"
            f"Research:\n{summary}\n"
            f"{ticker_block}\n"
            f"Risk:\n{risk_narrative}\n"
            f"{portfolio_block}"
            f"{calibration_block}\n"
            f"Produce 5 trade ideas and portfolio strategy JSON. Use price tools for entry/stop/target levels."
        )
