"""
Risk Manager — evaluates risks based on gathered research data.

Now equipped with real measurement tools (correlation, factor loadings,
market breadth) instead of just narrative reasoning. The CRO can ask
"what's the actual 3-month correlation between AAPL and MSFT?" and get
the number, not the LLM's prior on it.
"""

import logging
import numpy as np
from langchain_core.tools import tool

from agents.base_agent import BaseAgent
from data.fred_client import FREDDataClient
from data.market_client import MarketDataClient

logger = logging.getLogger(__name__)

_fred = FREDDataClient()
_market = MarketDataClient()


@tool
def get_macro_snapshot() -> dict:
    """Get latest macro indicators for regime classification. Cached — cheap to call."""
    return _fred.get_macro_snapshot()


@tool
def get_vix_history(lookback_days: int = 60) -> list:
    """Get recent VIX history for volatility regime assessment."""
    return _fred.get_series_history("VIXCLS", lookback_days)


def _returns_for(ticker: str, period: str = "3mo") -> list[float]:
    """Helper: daily return series from total-return-adjusted closes."""
    bars = _market.get_total_return_history(ticker, period=period)
    if not bars or len(bars) < 20:
        return []
    closes = [b["close"] for b in bars if b.get("close")]
    return [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]


@tool
def get_realized_correlation(tickers: str, period: str = "3mo") -> dict:
    """
    Compute the realized correlation matrix for a comma-separated list of
    tickers (e.g. "AAPL,MSFT,GOOGL"). Returns the matrix, average pairwise
    correlation, and a "concentration_flag" for high-correlation clusters.

    Use this to verify or reject correlation-risk claims with actual numbers
    instead of intuition. A pair > 0.85 is effectively one position.
    """
    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    if len(ticker_list) < 2:
        return {"error": "Need 2+ tickers"}
    rets: dict[str, list[float]] = {}
    for tk in ticker_list[:8]:  # cap for API conservation
        r = _returns_for(tk, period)
        if r:
            rets[tk] = r
    if len(rets) < 2:
        return {"error": "Insufficient data after fetch"}
    n = min(len(v) for v in rets.values())
    M = np.array([rets[t][-n:] for t in rets])
    corr = np.corrcoef(M)
    out_tickers = list(rets.keys())
    matrix = [
        [round(float(corr[i, j]), 3) for j in range(len(out_tickers))]
        for i in range(len(out_tickers))
    ]
    pairs = [
        {"a": out_tickers[i], "b": out_tickers[j], "corr": matrix[i][j]}
        for i in range(len(out_tickers))
        for j in range(i + 1, len(out_tickers))
    ]
    pairs.sort(key=lambda p: abs(p["corr"]), reverse=True)
    avg_corr = float(np.mean([p["corr"] for p in pairs])) if pairs else 0.0
    high_pairs = [p for p in pairs if abs(p["corr"]) >= 0.85]
    return {
        "tickers": out_tickers,
        "matrix": matrix,
        "highest_pairs": pairs[:5],
        "avg_pairwise_correlation": round(avg_corr, 3),
        "concentration_flag": bool(high_pairs),
        "concentrated_pairs": high_pairs,
        "lookback_period": period,
        "n_observations": n,
    }


@tool
def get_factor_loadings(ticker: str, period: str = "6mo") -> dict:
    """
    Compute factor exposures for a single ticker against FF5-style + Low-Vol
    + Momentum proxy ETFs. Returns market beta, size/value/profitability/
    low_vol/momentum betas, alpha, alpha p-value, plus a `style_flag`
    summarizing the strongest factor exposure. (USMV-based low_vol stands
    in for the FF CMA "investment" factor — see quant.factors.)

    Use this to back up "this is a high-beta tech name" claims with actual
    regression numbers.
    """
    from quant.factors import build_proxy_factor_returns, compute_multi_factor_loadings
    rets = _returns_for(ticker, period)
    if not rets:
        return {"error": f"No price data for {ticker}"}
    proxies = build_proxy_factor_returns(period=period)
    if not proxies:
        return {"error": "Factor proxy ETFs unavailable"}
    n = min(len(rets), *[len(v) for v in proxies.values()])
    if n < 30:
        return {"error": f"Need 30+ overlapping observations (got {n})"}
    aligned = {k: v[-n:] for k, v in proxies.items()}
    rets_aligned = rets[-n:]
    result = compute_multi_factor_loadings(rets_aligned, aligned)
    if "error" in result:
        return result
    # Identify dominant style: largest absolute non-market beta
    betas = result.get("factor_betas", {})
    style_betas = {k: v for k, v in betas.items() if k != "market" and v is not None}
    if style_betas:
        dominant = max(style_betas.items(), key=lambda kv: abs(kv[1]))
        result["style_flag"] = f"{dominant[0]} ({dominant[1]:+.2f})"
    return {"ticker": ticker, **result}


@tool
def get_market_breadth() -> dict:
    """
    Snapshot of market breadth: how many of the 11 sector ETFs are above
    their 50-day moving average, and the % of mega-caps in uptrends. Wide
    breadth (>70% above 50DMA) = healthy; narrow (<30%) = late-cycle warning.
    """
    sector_etfs = ["XLK", "XLV", "XLF", "XLE", "XLY", "XLP", "XLI", "XLU", "XLB", "XLRE", "XLC"]
    mega_caps = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "BRK-B", "JPM", "V", "UNH"]
    above_50_sectors = 0
    sector_total = 0
    for tk in sector_etfs:
        try:
            bars = _market.get_price_history(tk, period="6mo")
            if bars and len(bars) >= 50:
                closes = [b["close"] for b in bars]
                ma50 = float(np.mean(closes[-50:]))
                if closes[-1] > ma50:
                    above_50_sectors += 1
                sector_total += 1
        except Exception as e:
            logger.debug(f"breadth: {tk} skip ({e})")
    above_50_megas = 0
    mega_total = 0
    for tk in mega_caps:
        try:
            bars = _market.get_price_history(tk, period="6mo")
            if bars and len(bars) >= 50:
                closes = [b["close"] for b in bars]
                ma50 = float(np.mean(closes[-50:]))
                if closes[-1] > ma50:
                    above_50_megas += 1
                mega_total += 1
        except Exception as e:
            logger.debug(f"breadth: {tk} skip ({e})")
    sector_pct = round(above_50_sectors / sector_total * 100, 1) if sector_total else None
    mega_pct = round(above_50_megas / mega_total * 100, 1) if mega_total else None
    if sector_pct is None:
        regime_flag = "unknown"
    elif sector_pct >= 70:
        regime_flag = "broad_strength"
    elif sector_pct >= 50:
        regime_flag = "mixed"
    elif sector_pct >= 30:
        regime_flag = "narrow"
    else:
        regime_flag = "broad_weakness"
    return {
        "sectors_above_50dma_pct": sector_pct,
        "sectors_above_50dma_count": above_50_sectors,
        "sectors_total": sector_total,
        "mega_caps_above_50dma_pct": mega_pct,
        "mega_caps_above_50dma_count": above_50_megas,
        "mega_caps_total": mega_total,
        "regime_flag": regime_flag,
    }


SYSTEM_PROMPT = """You are the Chief Risk Officer at a quantitative hedge fund. You evaluate
all research through a risk lens before any capital is deployed.

You have measurement tools — USE THEM. Risk claims must be backed by numbers,
not narrative:
  - get_realized_correlation(tickers) — actual N-month correlation matrix
    plus the 5 highest pairs and a concentration flag.
  - get_factor_loadings(ticker)        — FF5+Momentum betas with t-stats.
  - get_market_breadth()                — % sectors and mega-caps above 50DMA.
  - get_macro_snapshot() / get_vix_history(days)

Call get_realized_correlation FIRST when there are 2+ tickers in the analysis.
Call get_market_breadth ONCE per analysis as part of the macro read. Call
get_factor_loadings on tickers whose style/factor positioning is non-obvious.

Given the analysis plan and gathered research data, assess:

1. MACRO REGIME: Classify as EXPANSION, LATE_CYCLE, CONTRACTION, or RECOVERY.
   Use yield curve shape, credit spread levels, VIX regime, fed funds rate direction,
   employment trends, and inflation dynamics. Provide confidence (0-100).

2. POSITION-LEVEL RISKS: For each ticker, what could go wrong?
   Valuation risk, execution risk, regulatory risk, competitive threat, earnings risk.

3. CORRELATION RISKS: Use get_realized_correlation. Cite actual numbers. A
   concentration_flag=true response or any pair >= 0.85 is a critical risk.

4. FACTOR / STYLE RISKS: Use get_factor_loadings on key names. Note style
   concentration (all growth? all small-cap? all momentum?).

5. BREADTH: Use get_market_breadth. Narrow breadth (<30%) is late-cycle warning;
   broad weakness (<30% sectors above 50DMA) raises overall_risk_level.

6. TAIL RISKS: Low-probability, high-impact scenarios. Geopolitical shocks, policy
   surprises, liquidity events, black swan scenarios relevant to the themes.

7. REGULATORY/POLITICAL: Elections, legislative changes, antitrust, trade policy.

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
Be specific and quantitative in your risk assessments. Cite data from the research.

TOOL BUDGET: Use AT MOST 4 tool calls total. Prioritize:
  1. get_realized_correlation (always, when 2+ tickers in plan)
  2. get_market_breadth (always, once per analysis)
  3. get_factor_loadings (one ticker only, the most ambiguous one)
  4. get_macro_snapshot OR get_vix_history (only if research summary lacks the macro number you need)
After 4 calls, write the JSON. Do not loop."""


class RiskManager(BaseAgent):
    agent_name = "risk_manager"
    system_prompt = SYSTEM_PROMPT
    output_instructions = OUTPUT_INSTRUCTIONS
    # Hard cap. With 5 tools available a runaway agent would otherwise burn
    # the 90s budget. 5 iterations = up to 4 tool calls + final synthesis.
    max_iterations = 5

    def get_tools(self):
        return [
            get_macro_snapshot,
            get_vix_history,
            get_realized_correlation,
            get_factor_loadings,
            get_market_breadth,
        ]

    def build_input_prompt(self, context: dict) -> str:
        plan = context.get("plan", {})
        research = context.get("research", {})
        summary = research.get("data_summary", "No research data available.")
        # Cap summary to prevent context blowout
        if len(summary) > 2000:
            summary = summary[:2000] + "..."

        # Structured ticker data — passes raw fundamentals/sentiment/options
        # alongside the prose summary so Risk Manager doesn't have to reverse-
        # engineer numbers from the narrative.
        ticker_data = research.get("ticker_data") or {}
        structured_block = ""
        if ticker_data:
            lines = []
            for tk, td in list(ticker_data.items())[:6]:
                if not isinstance(td, dict):
                    continue
                fund = td.get("fundamentals") or {}
                sentiment = td.get("sentiment") or {}
                pe = fund.get("pe_ratio")
                margin = fund.get("profit_margin")
                growth = fund.get("revenue_growth")
                beta = fund.get("beta")
                sector = fund.get("sector")
                short_ratio = fund.get("short_ratio")
                line = (
                    f"  {tk}: sector={sector} P/E={pe} margin={margin} "
                    f"rev_growth={growth} beta={beta} short_ratio={short_ratio}"
                )
                if isinstance(sentiment, dict) and sentiment.get("compound") is not None:
                    line += f" sent={sentiment.get('compound')}"
                lines.append(line)
            if lines:
                structured_block = "\n=== STRUCTURED TICKER DATA ===\n" + "\n".join(lines) + "\n"

        # Falsification criteria — score each one explicitly with a probability.
        # Used by CIO to frame "what would change our view" in the memo.
        falsification = plan.get("falsification_criteria") or []
        falsification_block = ""
        if falsification:
            falsification_block = (
                "\n=== FALSIFICATION CRITERIA TO SCORE ===\n"
                "For EACH criterion below, assess the probability it materializes "
                "in the time horizon. Add to your output as `falsification_probabilities`:\n"
                "[{criterion, probability: 'low|medium|high', reasoning}]\n"
                + "\n".join(f"  - {c}" for c in falsification)
            )

        question_type = plan.get("question_type") or ""
        risk_focus = plan.get("risk_focus") or []
        focus_directive = ""
        if "concentration" in risk_focus or "correlation" in risk_focus:
            focus_directive = "Call get_realized_correlation FIRST; concentration is the priority risk this query.\n"
        elif "factor" in risk_focus:
            focus_directive = "Call get_factor_loadings on the primary ticker FIRST; factor exposure is the priority.\n"
        elif "tail" in risk_focus or question_type == "hedging":
            focus_directive = "Call get_market_breadth FIRST; check macro stress indicators (VIX, credit) before per-ticker.\n"

        return (
            f"Query: {plan.get('query', '')} | Question type: {question_type} | "
            f"Tickers: {', '.join(plan.get('tickers', []))} | Risk Focus: {', '.join(risk_focus)}\n\n"
            f"Research Summary:\n{summary}\n"
            f"{structured_block}"
            f"{falsification_block}\n"
            f"{focus_directive}"
            f"Use get_realized_correlation, get_market_breadth, get_factor_loadings as needed.\n"
            f"Evaluate the risks and produce your risk assessment JSON, including "
            f"`falsification_probabilities` if the plan provided falsification_criteria."
        )
