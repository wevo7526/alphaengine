"""
MCP surface (T8) — the agent's door, model-agnostic.

Exposes the six deterministic quant_core tools over MCP (streamable HTTP) so any
MCP-capable client (Claude Desktop, a fund's agent, etc.) can discover and call
them. Same core + same SignalEnvelope header as the REST surface (api.py); the
two doors do not call each other. Auth + metering are shared with REST via the
gateway access dependency, applied here as ASGI middleware.

Run locally:   python server.py           (streamable HTTP on $PORT, default 8081)
Deploy:        ASGI app = `app` below, bound to 0.0.0.0:$PORT.

The agent-desk slate (the probabilistic plane) is added as an async job tool in
T7; this module ships the deterministic tools, which are enough to prove a live
MCP connection end to end.
"""

from __future__ import annotations

import os
from typing import Optional

from mcp.server.fastmcp import FastMCP

from api import DeterministicEnvelope, _now, _run
from contracts import TOOL_INPUTS, parse_input
from contracts.errors import ApiError

mcp = FastMCP("alphaengine")
# Serve the streamable endpoint at the app root so mounting it at "/mcp" in the
# combined deploy app (app.py) lands the MCP endpoint exactly at /mcp (not
# /mcp/mcp). Standalone `python server.py` then serves it at "/".
mcp.settings.streamable_http_path = "/"


def _call(tool: str, body: dict) -> dict:
    """Validate -> run quant_core -> versioned envelope. Typed error dict on failure."""
    try:
        model = parse_input(TOOL_INPUTS[tool], body)
        result = _run(tool, model)
        return DeterministicEnvelope(request_id="mcp", generated_at=_now(), tool=tool, result=result).model_dump()
    except ApiError as e:
        return e.to_dict("mcp")


# ── Validation tools ──────────────────────────────────────────────────────

@mcp.tool()
def deflated_sharpe(returns: list[float], n_trials: int, trials_sharpe_std: Optional[float] = None) -> dict:
    """Deflated Sharpe Ratio: is this return stream edge, or noise? Corrects the
    Sharpe for the number of trials tried and for non-normal returns. Returns the
    DSR, PSR, and a verdict. Needs >= 8 returns."""
    return _call("deflated_sharpe", {"returns": returns, "n_trials": n_trials, "trials_sharpe_std": trials_sharpe_std})


@mcp.tool()
def pbo_cscv(pnl_matrix: list[list[float]], n_splits: int = 10, max_combos: int = 2000) -> dict:
    """Probability of Backtest Overfitting via CSCV. pnl_matrix is (T observations
    x N strategy configs). Returns PBO and a verdict. Needs N>=2 configs."""
    return _call("pbo_cscv", {"pnl_matrix": pnl_matrix, "n_splits": n_splits, "max_combos": max_combos})


# ── Signal tools ────────────────────────────────────────────────────────────

@mcp.tool()
def compute_spread_signal(
    a_closes: list[float], b_closes: list[float],
    symbol_a: str = "A", symbol_b: str = "B",
    zscore_window: int = 60, stability_window: int = 60,
) -> dict:
    """Full pair analysis over two aligned close series: TLS hedge ratio,
    Engle-Granger cointegration p-value, OU half-life, spread z-score, rolling
    stability, and a discrete trade signal. Needs >= 126 aligned observations."""
    return _call("compute_spread_signal", {
        "a_closes": a_closes, "b_closes": b_closes, "symbol_a": symbol_a,
        "symbol_b": symbol_b, "zscore_window": zscore_window, "stability_window": stability_window,
    })


@mcp.tool()
def find_cointegrated_pairs(
    prices: dict[str, list[float]],
    zscore_window: int = 60, stability_window: int = 60, cointegrated_only: bool = True,
) -> dict:
    """Screen a universe of supplied price series for cointegrated pairs, sorted
    by ADF p-value. prices is {symbol: [close, ...]}. Needs >= 2 series."""
    return _call("find_cointegrated_pairs", {
        "prices": prices, "zscore_window": zscore_window,
        "stability_window": stability_window, "cointegrated_only": cointegrated_only,
    })


# ── Risk tools ────────────────────────────────────────────────────────────

@mcp.tool()
def compute_var_cvar(
    portfolio_returns: list[float], confidence: float = 0.95, horizon_days: int = 1,
    portfolio_value: float = 100_000.0, bootstrap_samples: int = 1000,
) -> dict:
    """Portfolio VaR (parametric + Cornish-Fisher + historical bootstrap) and CVaR
    on a supplied daily return stream. Needs >= 20 returns."""
    return _call("compute_var_cvar", {
        "portfolio_returns": portfolio_returns, "confidence": confidence,
        "horizon_days": horizon_days, "portfolio_value": portfolio_value, "bootstrap_samples": bootstrap_samples,
    })


@mcp.tool()
def decompose_factors(
    portfolio_returns: list[float], factor_returns: dict[str, list[float]],
    risk_free_rate: Optional[float] = None,
) -> dict:
    """Multi-factor regression (HAC OLS): factor betas, alpha, R-squared, and a
    VIF multicollinearity diagnostic. factor_returns is {factor: [ret, ...]}.
    Needs >= 30 aligned observations."""
    return _call("decompose_factors", {
        "portfolio_returns": portfolio_returns, "factor_returns": factor_returns, "risk_free_rate": risk_free_rate,
    })


# ── ASGI app + shared auth/metering ────────────────────────────────────────

def _build_app():
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    from gateway.access import meter, resolve_identity

    app = mcp.streamable_http_app()

    class GatewayAuth(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            try:
                identity = resolve_identity(request)  # AUTH_STUB bypasses locally
                meter(identity)
            except ApiError as e:
                return JSONResponse(e.to_dict("mcp"), status_code=e.http_status)
            return await call_next(request)

    app.add_middleware(GatewayAuth)
    return app


app = _build_app()


if __name__ == "__main__":
    mcp.settings.port = int(os.getenv("PORT", "8081"))
    mcp.settings.host = "0.0.0.0"
    mcp.run(transport="streamable-http")
