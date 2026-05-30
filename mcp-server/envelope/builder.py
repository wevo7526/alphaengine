"""
Map an IntelligenceMemo (the backend's real slate) → SignalEnvelope.

This is a projection, not new analysis: every field is sourced from the memo
(see docs/SIGNAL_ENVELOPE.md §3). The risk gate **reuses the existing Decision
Gate** (`agents/desk5_decision_gate.compute_decision`) — GO→pass, WATCH→warn,
NO-GO→block — run per idea so each signal carries its own gate. The Decision
Gate is imported from the backend (the gateway ships with it); if it isn't on
the path we fall back to the memo's portfolio-level `decision`.

Validation is intentionally sparse on the agent plane today: the memo doesn't
carry a per-idea deflated Sharpe, so `verdict` stays "inconclusive" — the
envelope never claims "edge" without a populated validation figure. Wiring
quant_core.deflated_sharpe per idea (the validation gate) is what later promotes
a verdict to edge / likely_noise.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from envelope.models import (
    Context,
    Instrument,
    Levels,
    Provenance,
    Risk,
    Signal,
    SignalEnvelope,
    Sizing,
    Validation,
)

try:  # reuse the real Decision Gate; fall back to the memo's decision if absent
    from agents.desk5_decision_gate import compute_decision as _compute_decision
except Exception:  # noqa: BLE001
    _compute_decision = None

_GATE_MAP = {"GO": "pass", "WATCH": "warn", "NO-GO": "block"}
_FLOAT_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _first_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    m = _FLOAT_RE.search(str(val))
    return float(m.group()) if m else None


def _side(direction: str) -> str:
    return "short" if "bearish" in (direction or "").lower() else "long"


def _gate_for_idea(idea: dict, macro_regime: str, risk_level: str, memo_decision: str) -> str:
    if _compute_decision is not None:
        try:
            d = _compute_decision([idea], macro_regime, risk_level)
            return _GATE_MAP.get(d.get("decision", "WATCH"), "warn")
        except Exception:  # noqa: BLE001
            pass
    return _GATE_MAP.get((memo_decision or "WATCH").upper(), "warn")


def _provenance_from_citations(citations: list[dict]) -> list[Provenance]:
    out: list[Provenance] = []
    for c in citations or []:
        if not isinstance(c, dict):
            continue
        out.append(Provenance(
            field="thesis",
            tool=str(c.get("source_type") or "citation"),
            inputs_hash=str(c.get("source_id") or c.get("url") or ""),
            formula=str(c.get("label") or c.get("excerpt") or ""),
        ))
    return out


def build_envelope_from_memo(
    memo: dict,
    *,
    request_id: str,
    engine_version: str,
    determinism: str = "agent",
    generated_at: Optional[str] = None,
) -> SignalEnvelope:
    macro_regime = memo.get("macro_regime") or "unknown"
    risk_level = memo.get("overall_risk_level") or "elevated"
    memo_decision = memo.get("decision") or "WATCH"
    falsification = list(memo.get("falsification_criteria") or [])
    mandate_warnings = list(memo.get("mandate_warnings") or [])
    macro_ctx = memo.get("macro_context") or {}
    regime_posterior = macro_ctx.get("regime_posterior") if isinstance(macro_ctx, dict) else None

    signals: list[Signal] = []
    for i, idea in enumerate(memo.get("trade_ideas") or []):
        if not isinstance(idea, dict):
            continue
        ticker = (idea.get("ticker") or "").upper()
        structure = idea.get("structure_type") or "outright"
        idea_id = f"{ticker.lower()}-{structure}-{i:02d}"

        size_pct = idea.get("position_size_pct") or 0
        weight = float(size_pct) / 100.0 if size_pct else None
        instruments = [Instrument(symbol=ticker, side=_side(idea.get("direction", "")), weight=weight)]
        if structure == "pair" and idea.get("pair_short_leg"):
            instruments.append(Instrument(symbol=str(idea["pair_short_leg"]).upper(), side="short"))

        regime_mult = None
        rc = idea.get("regime_conditional_size_pct")
        if rc and size_pct:
            regime_mult = round(float(rc) / float(size_pct), 3)

        factor_betas = None
        if idea.get("beta_to_spy") is not None:
            factor_betas = {"spy": float(idea["beta_to_spy"])}

        signals.append(Signal(
            idea_id=idea_id,
            instruments=instruments,
            thesis=(idea.get("thesis") or None) if determinism == "agent" else None,
            levels=Levels(
                entry=_first_float(idea.get("entry_zone")),
                stop=_first_float(idea.get("stop_loss")),
                target=_first_float(idea.get("take_profit")),
            ),
            sizing=Sizing(suggested_weight=weight, regime_multiplier=regime_mult),
            # No per-idea overfitting check in the memo → verdict stays
            # inconclusive. The structural rule guarantees we never say "edge".
            validation=Validation(verdict="inconclusive"),
            risk=Risk(
                factor_betas=factor_betas,
                gate=_gate_for_idea(idea, macro_regime, risk_level, memo_decision),
            ),
            context=Context(regime=macro_regime, regime_posterior=regime_posterior),
            falsification_criteria=falsification,
            mandate_warnings=mandate_warnings,
            provenance=_provenance_from_citations(idea.get("citations") or []),
        ))

    warnings: list[str] = []
    if (memo.get("data_quality") or "complete") != "complete":
        warnings.append(f"data_quality={memo.get('data_quality')}")
    if memo.get("verification_status") and memo["verification_status"] != "verified":
        warnings.append(f"verification_status={memo['verification_status']}")
    warnings.extend(mandate_warnings)

    return SignalEnvelope(
        engine_version=engine_version,
        request_id=request_id,
        generated_at=generated_at or str(memo.get("timestamp") or ""),
        determinism=determinism,  # type: ignore[arg-type]
        signals=signals,
        warnings=warnings,
    )
