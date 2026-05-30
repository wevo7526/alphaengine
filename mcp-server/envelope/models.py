"""
SignalEnvelope v1 — the single, semver'd output contract both planes emit.

Pydantic v2 models per docs/SIGNAL_ENVELOPE.md. The one structural rule lives
here and is unit-tested: a signal with `validation.verdict == "edge"` is
rejected unless a rigor figure (deflated_sharpe / pbo / psr) is populated. The
envelope structurally refuses to ship an idea it hasn't checked for overfitting.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0.0"

Side = Literal["long", "short"]
Determinism = Literal["exact", "agent"]
Verdict = Literal["edge", "inconclusive", "likely_noise"]
Gate = Literal["pass", "warn", "block"]


class Instrument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str
    side: Side
    weight: Optional[float] = None
    hedge_ratio: Optional[float] = None


class Levels(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entry: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None


class Sizing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suggested_weight: Optional[float] = None
    var_contribution: Optional[float] = None
    regime_multiplier: Optional[float] = None


class Validation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deflated_sharpe: Optional[float] = None
    pbo: Optional[float] = None
    psr: Optional[float] = None
    n_trials: Optional[int] = None
    verdict: Verdict = "inconclusive"

    def has_rigor(self) -> bool:
        """True iff at least one overfitting figure is populated."""
        return any(v is not None for v in (self.deflated_sharpe, self.pbo, self.psr))


class Risk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    var: Optional[float] = None
    cvar: Optional[float] = None
    factor_betas: Optional[dict[str, float]] = None
    stress: Optional[dict[str, float]] = None
    gate: Gate = "warn"


class Context(BaseModel):
    model_config = ConfigDict(extra="forbid")
    regime: Optional[str] = None
    regime_posterior: Optional[dict[str, float]] = None


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    tool: str
    inputs_hash: str
    formula: str


class Signal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idea_id: str
    instruments: list[Instrument] = Field(default_factory=list)
    thesis: Optional[str] = None
    levels: Levels = Field(default_factory=Levels)
    sizing: Sizing = Field(default_factory=Sizing)
    validation: Validation = Field(default_factory=Validation)
    risk: Risk = Field(default_factory=Risk)
    context: Context = Field(default_factory=Context)
    falsification_criteria: list[str] = Field(default_factory=list)
    mandate_warnings: list[str] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)

    @model_validator(mode="after")
    def _edge_requires_validation(self) -> "Signal":
        # THE MOAT, structural: never ship `edge` without an overfitting check.
        if self.validation.verdict == "edge" and not self.validation.has_rigor():
            raise ValueError(
                "verdict 'edge' requires a populated validation figure "
                "(deflated_sharpe, pbo, or psr) — the envelope refuses to ship "
                "an idea it hasn't checked for overfitting"
            )
        return self


class SignalEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = SCHEMA_VERSION
    engine_version: str
    request_id: str
    generated_at: str
    determinism: Determinism
    signals: list[Signal] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
