"""
T8 tests — the MCP surface. Verifies the tools are registered, callable, and
return the same versioned envelope as REST (golden-consistent through MCP), and
that the ASGI app builds.
"""

import asyncio

import numpy as np

import server


def test_tools_registered():
    tools = asyncio.run(server.mcp.list_tools())
    names = {t.name for t in tools}
    assert {
        "deflated_sharpe", "pbo_cscv", "compute_spread_signal",
        "find_cointegrated_pairs", "compute_var_cvar", "decompose_factors",
    } <= names


def test_deflated_sharpe_tool_golden():
    returns = np.random.default_rng(42).normal(0.0008, 0.018, 300).tolist()
    env = server.deflated_sharpe(returns, 50)
    assert env["determinism"] == "exact"
    assert env["tool"] == "deflated_sharpe"
    assert env["result"]["deflated_sharpe"] == 0.0134
    assert env["result"]["verdict"] == "likely_noise"


def test_var_cvar_tool():
    rng = np.random.default_rng(99)
    rets = (rng.normal(0.0005, 0.012, 500) - 0.0008 * (rng.random(500) > 0.95)).tolist()
    env = server.compute_var_cvar(rets)
    assert env["result"]["parametric"]["var_pct"] == 2.02


def test_tool_typed_error():
    env = server.deflated_sharpe([0.01, 0.02], 10)  # too few
    assert env["error"]["code"] == "INSUFFICIENT_OBSERVATIONS"


def test_asgi_app_builds():
    assert server.app is not None
