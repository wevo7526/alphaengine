"""
Risk Manager — evaluates risks based on gathered research data.

Mostly pure reasoning over the Research Analyst's output, with 2 lightweight
macro tools as a safety valve for additional data if needed.
"""

from langchain_core.tools import tool

from agents.base_agent import BaseAgent
from data.fred_client import FREDDataClient

_fred = FREDDataClient()


@tool
def get_macro_snapshot() -> dict:
    """Get latest macro indicators for regime classification. Cached — cheap to call."""
    return _fred.get_macro_snapshot()


@tool
def get_vix_history(lookback_days: int = 60) -> list:
    """Get recent VIX history for volatility regime assessment."""
    return _fred.get_series_history("VIXCLS", lookback_days)


SYSTEM_PROMPT = """You are the Chief Risk Officer at a quantitative hedge fund. You evaluate
all research through a risk lens before any capital is deployed.

Given the analysis plan and gathered research data, assess:

1. MACRO REGIME: Classify as EXPANSION, LATE_CYCLE, CONTRACTION, or RECOVERY.
   Use yield curve shape, credit spread levels, VIX regime, fed funds rate direction,
   employment trends, and inflation dynamics. Provide confidence (0-100).

2. POSITION-LEVEL RISKS: For each ticker in the analysis, what could go wrong?
   Valuation risk, execution risk, regulatory risk, competitive threat, earnings risk.

3. CORRELATION RISKS: Are proposed positions correlated? Sector concentration?
   Factor exposure (all growth? all cyclical?)? Crowding risk?

4. TAIL RISKS: Low-probability, high-impact scenarios. Geopolitical shocks, policy
   surprises, liquidity events, black swan scenarios relevant to the themes.

5. REGULATORY/POLITICAL: Elections, legislative changes, antitrust, trade policy.

Rate each risk factor:
- severity: low | medium | high | critical
- probability: low | medium | high
- mitigation: specific hedging or management strategy

Your overall_risk_level directly affects downstream position sizing:
- low: full sizing
- moderate: 75%
- elevated: 50%
- high: 25%
- extreme: no new positions

Respond with JSON:
{{
    "macro_regime": "EXPANSION | LATE_CYCLE | CONTRACTION | RECOVERY",
    "regime_confidence": <0-100>,
    "risk_factors": [
        {{
            "category": "macro | position | correlation | tail | regulatory | geopolitical",
            "description": "...",
            "severity": "low | medium | high | critical",
            "probability": "low | medium | high",
            "mitigation": "..."
        }}
    ],
    "overall_risk_level": "low | moderate | elevated | high | extreme",
    "risk_narrative": "<2-3 paragraph cohesive risk assessment>"
}}"""

OUTPUT_INSTRUCTIONS = """Respond with a single JSON object matching the schema above.
Be specific and quantitative in your risk assessments. Cite data from the research."""


class RiskManager(BaseAgent):
    agent_name = "risk_manager"
    system_prompt = SYSTEM_PROMPT
    output_instructions = OUTPUT_INSTRUCTIONS

    def get_tools(self):
        return [get_macro_snapshot, get_vix_history]

    def build_input_prompt(self, context: dict) -> str:
        plan = context.get("plan", {})
        research = context.get("research", {})
        summary = research.get("data_summary", "No research data available.")

        return (
            f"Analysis Plan:\n"
            f"  Query: {plan.get('query', '')}\n"
            f"  Intent: {plan.get('intent', '')}\n"
            f"  Tickers: {', '.join(plan.get('tickers', []))}\n"
            f"  Themes: {', '.join(plan.get('themes', []))}\n"
            f"  Risk Focus: {', '.join(plan.get('risk_focus', []))}\n\n"
            f"Research Data Summary:\n{summary}\n\n"
            f"Evaluate the risks and produce your risk assessment JSON."
        )
