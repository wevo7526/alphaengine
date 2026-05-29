"""
Stage 1 — Compute. Harvest a Fact Sheet from everything the desks already
produced, so the narration LLM has a closed set of pre-computed, pre-sourced
facts to cite (and nothing else).

This deliberately reuses the existing pipeline's outputs rather than re-running
analysis: the desks have already fetched prices, computed risk numbers, and
sized trade ideas. The compute stage's job is to bind each of those to a
receipt with a named formula / source, per Build Plan §1.3.

Receipt sources, in order of citation value:
  1. Trade-idea numeric fields (entry/stop/target/R-R/size/conviction/beta) —
     DoD requires each to trace to a computed receipt with a named formula.
  2. Macro indicators (VIX, credit, yield curve, fed funds) + regime.
  3. Live prices prefetched for the slate.
  4. Lineage sources (every tool call) → source receipts the qualitative
     claims (Key Findings, Risk Factors) can bind to.
"""

from __future__ import annotations

import logging

from provenance import FactSheet, computed_receipt, source_receipt

logger = logging.getLogger(__name__)

# lineage source_type → evidence source_name
_SRC_NAME = {
    "fred_series": "fred",
    "market_price": "yahoo",
    "sec_filing": "sec",
    "sec_insider": "sec",
    "sec_13f": "sec",
    "news_article": "newsapi",
    "web_search": "firecrawl",
    "technical": "alpha_vantage",
    "screen": "engine",
    "computed": "engine",
}

# Trade-idea fields that are quantitative claims requiring a computed receipt.
_TRADE_NUMERIC_FIELDS = [
    ("entry_zone", "entry zone"),
    ("stop_loss", "stop loss"),
    ("take_profit", "take profit"),
    ("risk_reward_ratio", "R/R"),
    ("position_size_pct", "position size %"),
    ("conviction", "conviction"),
    ("beta", "beta"),
    ("net_beta", "net beta"),
]

_MACRO_FIELDS = [
    ("vix", "VIX"),
    ("credit_spreads", "HY credit spread"),
    ("yield_curve", "yield curve 10Y-2Y"),
    ("fed_funds_rate", "fed funds rate"),
]


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def build_fact_sheet(
    *,
    macro_context: dict | None = None,
    strategy_data: dict | None = None,
    risk_data: dict | None = None,
    live_prices: dict | None = None,
    lineage: dict | None = None,
    extra_receipts: list[dict] | None = None,
) -> FactSheet:
    """Assemble the Fact Sheet. Never raises — a thin sheet is better than none.

    `extra_receipts` are pre-built receipt dicts (e.g. Phase-2 NLP source
    receipts: changed filing passages, hedged transcript sentences) that are
    added verbatim so the narrator can cite them as evidence.
    """
    fs = FactSheet()
    macro_context = macro_context or {}
    strategy_data = strategy_data or {}
    risk_data = risk_data or {}
    live_prices = live_prices or {}
    lineage = lineage or {}

    try:
        # 2. Macro indicators (do these first so they get low, memorable ids).
        for key, label in _MACRO_FIELDS:
            v = macro_context.get(key)
            if _is_num(v):
                fs.add(computed_receipt(
                    label, float(v),
                    formula_ref="data.fred.get_macro_snapshot",
                    source_name="fred",
                ))
        regime = macro_context.get("current_regime")
        if regime:
            fs.add(computed_receipt(
                "macro regime", regime,
                formula_ref="quant.regime.classify_regime",
                inputs={k: macro_context.get(k) for k, _ in _MACRO_FIELDS},
                source_name="engine",
            ))

        # 3. Live prices.
        for tk, px in (live_prices or {}).items():
            if _is_num(px):
                fs.add(computed_receipt(
                    f"{tk} price", float(px),
                    formula_ref="data.market.get_fundamentals",
                    source_name="yahoo", ticker=tk,
                ))

        # 1. Trade-idea numeric fields — the DoD-critical receipts.
        for idea in (strategy_data.get("trade_ideas") or []):
            if not isinstance(idea, dict):
                continue
            tk = (idea.get("ticker") or "").upper() or None
            for field, label in _TRADE_NUMERIC_FIELDS:
                if field not in idea:
                    continue
                val = idea.get(field)
                if val in (None, "", "?"):
                    continue
                # Keep numbers numeric; keep ranges/strings as-is (the display
                # string still carries the digits for validation matching).
                fs.add(computed_receipt(
                    f"{tk or '?'} {label}", float(val) if _is_num(val) else val,
                    formula_ref="agents.portfolio_strategist.trade_idea",
                    inputs={"ticker": tk, "field": field},
                    source_name="engine", ticker=tk,
                ))

        # 4. Lineage sources → source receipts for qualitative grounding.
        for src in (lineage.get("sources") or []):
            if not isinstance(src, dict):
                continue
            stype = src.get("type") or "computed"
            sid = src.get("id")
            if not sid:
                continue
            label = f"{src.get('tool', stype)}: {sid}"
            # We don't persist the raw observation text yet, so the passage is
            # the source label — enough for the citation to resolve to a real,
            # auditable tool call. TODO(alpha): persist tool-result excerpts as
            # passages in Phase 2 when EDGAR/Firecrawl text is harvested.
            fs.add(source_receipt(
                _SRC_NAME.get(stype, "engine"),
                str(sid),
                label,
                ticker=(src.get("ticker") or None),
                url=src.get("url"),
                label=label,
            ))

        # 5. Pre-built NLP source receipts (filing-change passages, hedged
        #    transcript sentences, 8-K novelty) — already content-hashed.
        for r in (extra_receipts or []):
            if isinstance(r, dict) and r.get("content_hash"):
                fs.add(r)
    except Exception as e:  # noqa: BLE001 — compute must never break the memo
        logger.warning(f"[pipeline.compute] fact-sheet harvest partial: {e}")

    logger.info("[pipeline.compute] Fact Sheet built: %d entries", len(fs))
    return fs
