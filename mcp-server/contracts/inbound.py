"""
Inbound data contracts for the deterministic tools.

One Pydantic model per tool defines the request body shape; a `parse_input`
helper turns a raw dict into a validated model, translating Pydantic shape
failures into a typed SCHEMA_INVALID error and domain failures (too few
observations) into INSUFFICIENT_OBSERVATIONS. A payload-size guard runs first so
oversize bodies fail fast with INPUT_TOO_LARGE rather than allocating.

No truncation — we warn or reject, never silently shrink the caller's data
(build spec risk note). Large-universe data-by-reference is a v2 concern; the
inline caps below bound beta payloads.
"""

from __future__ import annotations

from typing import Optional, Type, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from contracts.errors import InputTooLarge, InsufficientObservations, SchemaInvalid

# Inline payload caps for the beta (data-by-reference removes these in v2).
MAX_BODY_BYTES = 8 * 1024 * 1024        # 8 MB raw request body
MAX_TOTAL_FLOATS = 2_000_000            # ~ a few hundred series of daily bars
MAX_SERIES = 500                        # universe breadth for find_cointegrated_pairs


def guard_body_size(raw_len_bytes: int) -> None:
    if raw_len_bytes > MAX_BODY_BYTES:
        raise InputTooLarge(
            f"request body {raw_len_bytes} bytes exceeds the {MAX_BODY_BYTES}-byte cap",
            details={"limit_bytes": MAX_BODY_BYTES, "got_bytes": raw_len_bytes},
        )


def _count_floats(obj) -> int:
    if isinstance(obj, (int, float)):
        return 1
    if isinstance(obj, dict):
        return sum(_count_floats(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return sum(_count_floats(v) for v in obj)
    return 0


def guard_float_count(body: dict) -> None:
    n = _count_floats(body)
    if n > MAX_TOTAL_FLOATS:
        raise InputTooLarge(
            f"payload carries {n} numbers, over the {MAX_TOTAL_FLOATS} cap — "
            f"use a smaller universe (data-by-reference is a v2 feature)",
            details={"limit_floats": MAX_TOTAL_FLOATS, "got_floats": n},
        )


# ── per-tool input schemas ───────────────────────────────────────────────

class DeflatedSharpeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    returns: list[float]
    n_trials: int = Field(ge=1)
    trials_sharpe_std: Optional[float] = None

    def assert_ready(self) -> None:
        if len(self.returns) < 8:
            raise InsufficientObservations(
                f"deflated_sharpe needs >= 8 returns, got {len(self.returns)}",
                details={"need": 8, "got": len(self.returns)},
            )


class PboInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pnl_matrix: list[list[float]]  # T observations x N configs
    n_splits: int = Field(default=10, ge=2)
    max_combos: int = Field(default=2000, ge=1)

    def assert_ready(self) -> None:
        rows = len(self.pnl_matrix)
        cols = len(self.pnl_matrix[0]) if rows else 0
        # Shape validity before sufficiency: ragged rows are malformed input.
        if any(len(r) != cols for r in self.pnl_matrix):
            raise SchemaInvalid("pnl_matrix rows must be equal length")
        if cols < 2:
            raise InsufficientObservations(
                "pbo_cscv needs >= 2 configurations (columns)",
                details={"need_cols": 2, "got_cols": cols},
            )
        if rows < self.n_splits * 2:
            raise InsufficientObservations(
                f"pbo_cscv needs >= {self.n_splits * 2} observations (rows), got {rows}",
                details={"need_rows": self.n_splits * 2, "got_rows": rows},
            )


class SpreadSignalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    a_closes: list[float]
    b_closes: list[float]
    symbol_a: str = "A"
    symbol_b: str = "B"
    zscore_window: int = Field(default=60, ge=2)
    stability_window: int = Field(default=60, ge=5)

    def assert_ready(self) -> None:
        n = min(len(self.a_closes), len(self.b_closes))
        if n < 126:
            raise InsufficientObservations(
                f"compute_spread_signal needs >= 126 aligned observations, got {n}",
                details={"need": 126, "got": n},
            )


class FindPairsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prices: dict[str, list[float]]
    candidates: Optional[list[tuple[str, str]]] = None
    zscore_window: int = Field(default=60, ge=2)
    stability_window: int = Field(default=60, ge=5)
    cointegrated_only: bool = True

    def assert_ready(self) -> None:
        if len(self.prices) < 2:
            raise InsufficientObservations(
                "find_cointegrated_pairs needs >= 2 price series",
                details={"need": 2, "got": len(self.prices)},
            )
        if len(self.prices) > MAX_SERIES:
            raise InputTooLarge(
                f"{len(self.prices)} series exceeds the {MAX_SERIES} cap",
                details={"limit": MAX_SERIES, "got": len(self.prices)},
            )


class VarCvarInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    portfolio_returns: list[float]
    confidence: float = Field(default=0.95, gt=0.5, lt=1.0)
    horizon_days: int = Field(default=1, ge=1)
    portfolio_value: float = Field(default=100_000.0, gt=0)
    bootstrap_samples: int = Field(default=1000, ge=100, le=100_000)

    def assert_ready(self) -> None:
        if len(self.portfolio_returns) < 20:
            raise InsufficientObservations(
                f"compute_var_cvar needs >= 20 returns, got {len(self.portfolio_returns)}",
                details={"need": 20, "got": len(self.portfolio_returns)},
            )


class DecomposeFactorsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    portfolio_returns: list[float]
    factor_returns: dict[str, list[float]]
    risk_free_rate: Optional[float] = None

    def assert_ready(self) -> None:
        if not self.factor_returns:
            raise SchemaInvalid("factor_returns must contain at least one factor")
        min_len = min(len(self.portfolio_returns), *[len(v) for v in self.factor_returns.values()])
        if min_len < 30:
            raise InsufficientObservations(
                f"decompose_factors needs >= 30 aligned observations, got {min_len}",
                details={"need": 30, "got": min_len},
            )


_M = TypeVar("_M", bound=BaseModel)


def parse_input(model_cls: Type[_M], body: dict) -> _M:
    """Validate a raw body into a tool input model.

    Raises typed ApiError subclasses: INPUT_TOO_LARGE (size), SCHEMA_INVALID
    (shape), INSUFFICIENT_OBSERVATIONS (domain). Pydantic shape failures are
    flattened into SCHEMA_INVALID with the offending fields in `details`.
    """
    if not isinstance(body, dict):
        raise SchemaInvalid("request body must be a JSON object")
    guard_float_count(body)
    try:
        model = model_cls(**body)
    except ValidationError as e:
        raise SchemaInvalid(
            f"{model_cls.__name__} failed validation",
            details={"errors": [{"loc": list(err["loc"]), "msg": err["msg"]} for err in e.errors()]},
        )
    # Domain readiness (observation counts etc.) — typed, not Pydantic.
    if hasattr(model, "assert_ready"):
        model.assert_ready()  # type: ignore[attr-defined]
    return model


# Registry: tool name -> input model. The REST/MCP surfaces dispatch off this.
TOOL_INPUTS: dict[str, Type[BaseModel]] = {
    "deflated_sharpe": DeflatedSharpeInput,
    "pbo_cscv": PboInput,
    "compute_spread_signal": SpreadSignalInput,
    "find_cointegrated_pairs": FindPairsInput,
    "compute_var_cvar": VarCvarInput,
    "decompose_factors": DecomposeFactorsInput,
}
