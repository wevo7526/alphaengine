# alphaengine (Python SDK)

Thin client for the AlphaEngine deterministic signal API. **Your data in, a
validated `SignalEnvelope` out. Nothing stored.**

```bash
pip install alphaengine
```

```python
from alphaengine import Client

ae = Client(api_key="ae_live_...")

# Risk on a return stream
env = ae.compute_var_cvar(portfolio_returns=my_returns)
print(env["result"]["cvar"]["cvar_pct"])      # Expected Shortfall, %

# Is it edge, or noise?
ds = ae.deflated_sharpe(my_returns, n_trials=240)["result"]
if ds["verdict"] != "likely_noise":
    ...  # route to execution

# Find cointegrated pairs in your own universe
pairs = ae.find_cointegrated_pairs({"AAA": a_closes, "BBB": b_closes})
```

Every method returns the versioned envelope (`schema_version`, `engine_version`,
`determinism: "exact"`, `tool`, `result`). Typed failures raise
`AlphaEngineError` with a machine-parseable `.code`
(`INSUFFICIENT_OBSERVATIONS`, `SCHEMA_INVALID`, `AUTH_MISSING`,
`QUOTA_EXCEEDED`, ...). See https://alphaengine.dev/docs.

Tools: `deflated_sharpe`, `pbo_cscv`, `compute_spread_signal`,
`find_cointegrated_pairs`, `compute_var_cvar`, `decompose_factors`.

> Status: beta. Repo-only for now; not yet published to PyPI.
