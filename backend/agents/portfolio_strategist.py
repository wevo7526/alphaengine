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
    "portfolio_positioning": "risk_on | risk_off | neutral | rotational",
    "hedging_recommendations": [
        "Buy SPY May 520 puts ($4.20) — portfolio beta hedge, protects against 5% drawdown",
        "Long VIX June 30 calls ($1.80) — tail risk insurance if vol spikes",
        "..."
    ],
    "strategy_narrative": "<1-2 paragraph strategy explanation>"
}}"""

OUTPUT_INSTRUCTIONS = """Use your price tools to get current levels for the tickers you want
to include in trade ideas, then respond with a single JSON object matching the schema above."""


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

        summary = research.get("data_summary", "No research data.")
        if len(summary) > 2000:
            summary = summary[:2000] + "..."
        risk_narrative = risk.get("risk_narrative", "")
        if len(risk_narrative) > 500:
            risk_narrative = risk_narrative[:500] + "..."

        return (
            f"Query: {plan.get('query', '')} | Tickers: {', '.join(plan.get('tickers', []))} | Horizon: {plan.get('time_horizon', 'weeks')}\n"
            f"Regime: {risk.get('macro_regime', '?')} | Risk: {risk.get('overall_risk_level', '?')}\n\n"
            f"Research:\n{summary}\n\n"
            f"Risk:\n{risk_narrative}\n\n"
            f"Produce 5 trade ideas and portfolio strategy JSON. Use price tools for entry/stop/target levels."
        )
