"""
20 lines: your prices in, a validated signal out.

Run against the deployed API:
    pip install alphaengine
    ALPHAENGINE_KEY=ae_live_... python first_signal.py

Nothing you send is stored. The deterministic plane is version-pinned, so the
`engine_version` on the envelope lets your algo reproduce or refuse a result.
"""

import os

from alphaengine import Client

ae = Client(api_key=os.getenv("ALPHAENGINE_KEY"), base_url=os.getenv("ALPHAENGINE_URL", "https://api.alphaengine.dev"))

# Your data. Passed in the call, computed, discarded. (Toy returns here.)
returns = [0.004, -0.011, 0.006, 0.013, -0.002, 0.009, -0.014, 0.007, 0.003,
           0.011, -0.006, 0.002, 0.008, -0.009, 0.005, 0.001, 0.010, -0.004,
           0.006, -0.003, 0.007, 0.012, -0.008, 0.004, 0.009, -0.005, 0.003, 0.006]

# 1) Risk on the book.
risk = ae.compute_var_cvar(portfolio_returns=returns)
print("engine:", risk["engine_version"], "| determinism:", risk["determinism"])
print("95% VaR:", risk["result"]["parametric"]["var_pct"], "% | CVaR:", risk["result"]["cvar"]["cvar_pct"], "%")

# 2) Is the edge real, or noise? Validate before you trade it.
ds = ae.deflated_sharpe(returns, n_trials=240)["result"]
verdict = ds["verdict"]
print("deflated Sharpe:", ds["deflated_sharpe"], "->", verdict)

# 3) Broker-routing stub: only act on a non-noise verdict.
if verdict != "likely_noise":
    print("route to execution ...")   # <- your algo / broker call goes here
else:
    print("skipped: the engine flagged this as likely noise")
