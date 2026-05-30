"""
alphaengine — thin Python client for the AlphaEngine deterministic API.

Your data in, a validated SignalEnvelope out. No data is stored; you pass it in
the call. Example:

    from alphaengine import Client
    ae = Client(api_key="ae_live_...")
    env = ae.compute_var_cvar(portfolio_returns=my_returns)
    print(env["result"]["cvar"]["cvar_pct"])

The deterministic plane is synchronous and version-pinned: read `engine_version`
off any envelope to reproduce or refuse a result. Typed errors raise
`AlphaEngineError` with a machine-parseable `.code`.
"""

from __future__ import annotations

from typing import Any, Optional

__version__ = "0.1.0"
__all__ = ["Client", "AlphaEngineError"]

DEFAULT_BASE_URL = "https://api.alphaengine.dev"


class AlphaEngineError(Exception):
    """A typed gateway error. Branch on `.code` (e.g. INSUFFICIENT_OBSERVATIONS,
    SCHEMA_INVALID, AUTH_MISSING, QUOTA_EXCEEDED)."""

    def __init__(self, code: str, message: str, request_id: Optional[str] = None):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.request_id = request_id


class Client:
    """Synchronous client for the deterministic tools.

    `session` is an escape hatch for testing: pass any object with httpx-style
    `.post(path, json=...)` / `.get(path)` (e.g. fastapi.testclient.TestClient)
    to run in-process. In normal use, leave it None and the client builds an
    httpx.Client bound to `base_url`.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        session: Any = None,
    ):
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        if session is not None:
            self._session = session
        else:
            import httpx  # imported lazily so tests can inject a session without httpx
            self._session = httpx.Client(base_url=base_url, timeout=timeout)

    # ── core ──
    def _post(self, tool: str, body: dict) -> dict:
        clean = {k: v for k, v in body.items() if v is not None}
        resp = self._session.post(f"/v1/tools/{tool}", json=clean, headers=self._headers)
        data = resp.json()
        if getattr(resp, "status_code", 200) >= 400 or (isinstance(data, dict) and "error" in data):
            err = data.get("error", {}) if isinstance(data, dict) else {}
            raise AlphaEngineError(err.get("code", "ERROR"), err.get("message", str(data)), err.get("request_id"))
        return data

    def health(self) -> dict:
        return self._session.get("/v1/health", headers=self._headers).json()

    def version(self) -> dict:
        return self._session.get("/v1/version", headers=self._headers).json()

    # ── validation ──
    def deflated_sharpe(self, returns, n_trials: int, trials_sharpe_std: Optional[float] = None) -> dict:
        return self._post("deflated_sharpe", {"returns": list(returns), "n_trials": n_trials, "trials_sharpe_std": trials_sharpe_std})

    def pbo_cscv(self, pnl_matrix, n_splits: int = 10, max_combos: int = 2000) -> dict:
        return self._post("pbo_cscv", {"pnl_matrix": pnl_matrix, "n_splits": n_splits, "max_combos": max_combos})

    # ── signals ──
    def compute_spread_signal(self, a_closes, b_closes, symbol_a: str = "A", symbol_b: str = "B",
                              zscore_window: int = 60, stability_window: int = 60) -> dict:
        return self._post("compute_spread_signal", {
            "a_closes": list(a_closes), "b_closes": list(b_closes), "symbol_a": symbol_a,
            "symbol_b": symbol_b, "zscore_window": zscore_window, "stability_window": stability_window,
        })

    def find_cointegrated_pairs(self, prices: dict, zscore_window: int = 60,
                                stability_window: int = 60, cointegrated_only: bool = True) -> dict:
        return self._post("find_cointegrated_pairs", {
            "prices": prices, "zscore_window": zscore_window,
            "stability_window": stability_window, "cointegrated_only": cointegrated_only,
        })

    # ── risk ──
    def compute_var_cvar(self, portfolio_returns, confidence: float = 0.95, horizon_days: int = 1,
                         portfolio_value: float = 100_000.0, bootstrap_samples: int = 1000) -> dict:
        return self._post("compute_var_cvar", {
            "portfolio_returns": list(portfolio_returns), "confidence": confidence, "horizon_days": horizon_days,
            "portfolio_value": portfolio_value, "bootstrap_samples": bootstrap_samples,
        })

    def decompose_factors(self, portfolio_returns, factor_returns: dict, risk_free_rate: Optional[float] = None) -> dict:
        return self._post("decompose_factors", {
            "portfolio_returns": list(portfolio_returns), "factor_returns": factor_returns, "risk_free_rate": risk_free_rate,
        })
