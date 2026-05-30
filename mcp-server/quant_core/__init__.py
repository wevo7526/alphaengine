"""
quant_core — the deterministic plane.

Pure functions over data supplied by the caller. Zero data-layer imports, zero
LLM, zero I/O, zero global state. Same input → same output, byte-for-byte, on
the pinned numeric stack (see ../requirements.txt). These are the functions the
deterministic REST surface (api.py) and the MCP deterministic tools (server.py)
both call directly, in-process — they are NOT reachable over the network from
each other; both doors call the same function here.

Lifted from backend/quant/* per MASTER_PLAN decision (copy, don't import) so the
gateway can pin its own deps and freeze golden fixtures independently of the
production backend. Keep the math identical to the source on copy; if a backend
function changes, re-copy and re-freeze the fixture deliberately.

Beta cut (6 tools):
  Signals     — find_cointegrated_pairs, compute_spread_signal   (pairs.py)
  Validation  — deflated_sharpe, pbo_cscv                        (validation.py)
  Risk        — compute_var_cvar, decompose_factors             (risk.py / factors.py)
"""

from quant_core.validation import deflated_sharpe, pbo_cscv
from quant_core.pairs import find_cointegrated_pairs, compute_spread_signal
from quant_core.risk import compute_var_cvar
from quant_core.factors import decompose_factors

__all__ = [
    # Validation
    "deflated_sharpe",
    "pbo_cscv",
    # Signals
    "find_cointegrated_pairs",
    "compute_spread_signal",
    # Risk
    "compute_var_cvar",
    "decompose_factors",
]

# engine_version is stamped on every SignalEnvelope so a consumer can reproduce
# or refuse a result. Bump on any change to a quant_core function's output.
ENGINE_VERSION = "quant_core@1.0.0"
