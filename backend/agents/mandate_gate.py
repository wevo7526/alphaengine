"""
agents/mandate_gate.py — Mandate enforcement on agent-emitted trade ideas.

The Portfolio Strategist's prompt asks it to respect the user's mandate
(long-only / long-short / market-neutral / macro / multi-strat), but
prompt-level guidance alone is brittle: under load the LLM still slips a
short into a long-only basket, or returns single-name longs to a macro PM.

This module is the deterministic safety net. It runs AFTER the Strategist
returns and BEFORE the memo is persisted. The contract:

- Returns the (possibly-filtered) trade_ideas list
- Emits a `mandate_warnings` list of human-readable strings for the memo
- NEVER raises — a buggy gate must not block memo emission. On internal
  error, fall through with empty warnings.

Mandate semantics (kept intentionally short so the rules live in one
readable place):

    long_only      → drop ideas with direction in {bearish, strong_bearish}
                     or structure_type in {puts, short, hedge}
    long_short     → no constraint
    market_neutral → require |net beta| < 0.15 across the slate; flag
                     if violated (don't drop — that's the Strategist's
                     job to rebalance)
    macro          → require ≥40% of slate be ETFs/index/futures or have
                     a clear macro theme; flag if violated
    multi_strat    → require ≥3 distinct style_labels across the slate
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


_BEARISH_DIRECTIONS = frozenset({"bearish", "strong_bearish", "short"})
_LONG_ONLY_BLOCKED_STRUCTURES = frozenset({"puts", "short", "hedge"})

# Tickers / structure types that count as "macro-style" exposure: broad
# ETFs, futures proxies, rates/credit/FX instruments, sector rotations.
# Curated rather than complete — Strategist outputs ETF tickers we can
# pattern-match. ETF ticker bucket via market_cap_bucket="etf" is the
# strongest signal we have without per-name lookup.
_MACRO_STRUCTURE_TYPES = frozenset({"spread", "pair", "hedge"})


def _direction_of(idea: dict) -> str:
    d = idea.get("direction")
    if hasattr(d, "value"):
        d = d.value
    return (d or "").lower()


def _structure_of(idea: dict) -> str:
    return (idea.get("structure_type") or "").lower()


def _market_cap_bucket_of(idea: dict) -> str:
    return (idea.get("market_cap_bucket") or "").lower()


def _is_macro_style_idea(idea: dict) -> bool:
    """Heuristic: does this idea look like a macro/cross-asset exposure?

    True for ETF-bucket names, pair/spread/hedge structures, or ideas
    tagged with style_label="macro". Used by the macro-mandate gate.
    """
    if _market_cap_bucket_of(idea) == "etf":
        return True
    if _structure_of(idea) in _MACRO_STRUCTURE_TYPES:
        return True
    style = (idea.get("style_label") or "").lower()
    return style == "macro"


def _apply_long_only(ideas: list[dict]) -> tuple[list[dict], list[str]]:
    """Drop short/put/hedge ideas. Emit a warning per drop."""
    kept: list[dict] = []
    warnings: list[str] = []
    for idea in ideas:
        if not isinstance(idea, dict):
            continue
        direction = _direction_of(idea)
        structure = _structure_of(idea)
        ticker = idea.get("ticker") or "?"
        if direction in _BEARISH_DIRECTIONS:
            warnings.append(
                f"MANDATE long_only: dropped {ticker} (direction={direction})."
            )
            continue
        if structure in _LONG_ONLY_BLOCKED_STRUCTURES:
            warnings.append(
                f"MANDATE long_only: dropped {ticker} (structure={structure})."
            )
            continue
        kept.append(idea)
    return kept, warnings


def _apply_market_neutral(ideas: list[dict]) -> tuple[list[dict], list[str]]:
    """Compute slate net beta. Flag if |net beta| > 0.15."""
    warnings: list[str] = []
    if not ideas:
        return ideas, warnings
    net_beta = 0.0
    contributors = 0
    for idea in ideas:
        if not isinstance(idea, dict):
            continue
        beta = idea.get("beta_to_spy")
        size = idea.get("position_size_pct")
        if beta is None or size is None:
            continue
        try:
            b = float(beta)
            s = float(size) / 100.0
        except (TypeError, ValueError):
            continue
        signed = b * s if _direction_of(idea) not in _BEARISH_DIRECTIONS else -b * s
        net_beta += signed
        contributors += 1
    if contributors and abs(net_beta) > 0.15:
        warnings.append(
            f"MANDATE market_neutral: slate net beta = {net_beta:+.2f} (target |β| < 0.15). "
            f"Add or resize hedges before taking these trades."
        )
    return ideas, warnings


def _apply_macro(ideas: list[dict]) -> tuple[list[dict], list[str]]:
    """Require ≥40% of ideas to be macro-style. Flag if not met."""
    warnings: list[str] = []
    if not ideas:
        return ideas, warnings
    n = len(ideas)
    macro_n = sum(1 for i in ideas if isinstance(i, dict) and _is_macro_style_idea(i))
    if n >= 3 and (macro_n / n) < 0.40:
        warnings.append(
            f"MANDATE macro: only {macro_n}/{n} ideas are cross-asset/ETF/pair. "
            f"A macro mandate expects ≥40% — consider replacing single-name longs with "
            f"index ETF, futures proxy, or pair-trade structures."
        )
    return ideas, warnings


def _apply_multi_strat(ideas: list[dict]) -> tuple[list[dict], list[str]]:
    """Require ≥3 distinct style_labels across the slate."""
    warnings: list[str] = []
    if not ideas or len(ideas) < 5:
        return ideas, warnings
    labels = set()
    for idea in ideas:
        if not isinstance(idea, dict):
            continue
        label = (idea.get("style_label") or "").lower().strip()
        if label:
            labels.add(label)
    if len(labels) < 3:
        warnings.append(
            f"MANDATE multi_strat: only {len(labels)} distinct style_labels across "
            f"{len(ideas)} ideas. Aim for ≥3 styles for true diversification."
        )
    return ideas, warnings


_GATE_BY_MANDATE = {
    "long_only": _apply_long_only,
    "long_short": None,  # No constraint
    "market_neutral": _apply_market_neutral,
    "macro": _apply_macro,
    "multi_strat": _apply_multi_strat,
}


def enforce_mandate(
    trade_ideas: list[dict],
    mandate: str | None,
) -> tuple[list[dict], list[str]]:
    """Apply mandate-specific filtering + warnings to a trade-idea slate.

    Returns (filtered_ideas, warnings). Both always returned; never raises.
    `mandate` is matched case-insensitively; unknown mandates pass through.
    """
    if not trade_ideas:
        return trade_ideas, []
    if not mandate:
        return trade_ideas, []
    gate = _GATE_BY_MANDATE.get(mandate.lower())
    if gate is None:
        return trade_ideas, []
    try:
        return gate(trade_ideas)
    except Exception as e:
        logger.warning(f"mandate_gate.enforce_mandate failed (mandate={mandate}): {e}")
        return trade_ideas, []
