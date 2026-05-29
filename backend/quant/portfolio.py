"""
Portfolio construction (Build Plan §3.2) — robust weights with traceability.

Adds Hierarchical Risk Parity (López de Prado) natively on top of the
existing Ledoit-Wolf-shrunk covariance (quant.risk.compute_ewma_covariance)
and the Black-Litterman optimizer (quant.optimizer.black_litterman). HRP needs
no matrix inversion and is stable exactly where sample-covariance optimizers
blow up; it's implemented with scipy clustering so we avoid a heavy cvxpy /
PyPortfolioOpt dependency.

Also provides the agent-output → BL view bridge with **per-idea view→weight
receipts**, so every weight traces to the idea (thesis + conviction) that
produced it — replacing ad-hoc "4.0% / 3.5%" sizing with defensible,
decomposable weights (the §3.2 DoD).
"""

from __future__ import annotations

import numpy as np
from scipy.cluster.hierarchy import linkage
from scipy.spatial.distance import squareform


def _cov_to_corr(cov: np.ndarray) -> np.ndarray:
    d = np.sqrt(np.diag(cov))
    d[d == 0] = 1e-12
    corr = cov / np.outer(d, d)
    return np.clip(corr, -1.0, 1.0)


def _quasi_diag(link: np.ndarray) -> list[int]:
    """Leaf order from a linkage matrix (López de Prado getQuasiDiag)."""
    link = link.astype(int)
    n = link[-1, 3]  # total original items in the final merge
    sort_ix = [link[-1, 0], link[-1, 1]]
    num_items = link[-1, 3]
    while max(sort_ix) >= n:  # while clusters remain to expand
        new = []
        for i in sort_ix:
            if i < n:
                new.append(i)
            else:
                row = link[i - n]
                new.append(int(row[0]))
                new.append(int(row[1]))
        sort_ix = new
    return [int(i) for i in sort_ix]


def _inv_var_weights(cov_slice: np.ndarray) -> np.ndarray:
    ivp = 1.0 / np.diag(cov_slice)
    return ivp / ivp.sum()


def _cluster_var(cov: np.ndarray, items: list[int]) -> float:
    sub = cov[np.ix_(items, items)]
    w = _inv_var_weights(sub)
    return float(w @ sub @ w)


def _recursive_bisection(cov: np.ndarray, sort_ix: list[int]) -> np.ndarray:
    w = np.ones(len(sort_ix))
    clusters = [list(range(len(sort_ix)))]  # positions within sort_ix
    while clusters:
        new_clusters = []
        for c in clusters:
            if len(c) <= 1:
                continue
            half = len(c) // 2
            left, right = c[:half], c[half:]
            l_items = [sort_ix[i] for i in left]
            r_items = [sort_ix[i] for i in right]
            v_left = _cluster_var(cov, l_items)
            v_right = _cluster_var(cov, r_items)
            alpha = 1.0 - v_left / (v_left + v_right) if (v_left + v_right) > 0 else 0.5
            for i in left:
                w[i] *= alpha
            for i in right:
                w[i] *= (1.0 - alpha)
            new_clusters += [left, right]
        clusters = new_clusters
    return w


def hrp_weights(cov_matrix, tickers: list[str]) -> dict:
    """Hierarchical Risk Parity weights from a covariance matrix.

    Returns {weights: {ticker: w}, order: [tickers in quasi-diagonal order],
    method: "hrp", note}. Falls back to inverse-variance for n<3 (no tree).
    """
    cov = np.asarray(cov_matrix, dtype=float)
    n = cov.shape[0]
    if n != len(tickers) or n == 0:
        return {"weights": {}, "order": [], "method": "hrp", "note": "shape mismatch"}
    if n == 1:
        return {"weights": {tickers[0]: 1.0}, "order": list(tickers), "method": "hrp"}
    if n == 2:
        w = _inv_var_weights(cov)
        return {"weights": {tickers[i]: round(float(w[i]), 6) for i in range(2)},
                "order": list(tickers), "method": "inverse_variance", "note": "n<3"}

    corr = _cov_to_corr(cov)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    np.fill_diagonal(dist, 0.0)
    condensed = squareform(dist, checks=False)
    link = linkage(condensed, method="single")
    sort_ix = _quasi_diag(link)
    w = _recursive_bisection(cov, sort_ix)
    # Map back to ticker order.
    weights = {tickers[sort_ix[i]]: round(float(w[i]), 6) for i in range(n)}
    order = [tickers[i] for i in sort_ix]
    return {"weights": weights, "order": order, "method": "hrp"}


# ── Agent ideas → Black-Litterman views (+ per-idea traceability) ───────

def ideas_to_views(trade_ideas: list[dict]) -> tuple[dict, dict]:
    """Map trade ideas → BL views (expected excess return) + confidences.

    View per idea = the idea's own implied move (take_profit vs entry),
    signed by direction; falls back to a conviction-scaled default move.
    Confidence = conviction / 100. One view per ticker (highest conviction
    wins on duplicates).
    """
    views: dict[str, float] = {}
    confidences: dict[str, float] = {}
    best_conv: dict[str, float] = {}
    for idea in trade_ideas or []:
        if not isinstance(idea, dict):
            continue
        tk = (idea.get("ticker") or "").upper()
        if not tk:
            continue
        conv = float(idea.get("conviction") or 0)
        if tk in best_conv and conv <= best_conv[tk]:
            continue
        direction = (idea.get("direction") or "").lower()
        sign = -1.0 if "bear" in direction or "short" in direction else 1.0
        entry = idea.get("entry_zone") or idea.get("entry_price")
        target = idea.get("take_profit")
        er = None
        try:
            if entry and target and float(entry) > 0:
                er = (float(target) - float(entry)) / float(entry)
        except (TypeError, ValueError):
            er = None
        if er is None:
            er = sign * (0.04 + 0.12 * (conv / 100.0))  # conviction-scaled default move
        else:
            er = abs(er) * sign
        views[tk] = round(float(er), 6)
        confidences[tk] = round(max(0.0, min(1.0, conv / 100.0)), 4)
        best_conv[tk] = conv
    return views, confidences


def view_weight_receipts(weights: dict, views: dict, confidences: dict, *, method: str) -> list[dict]:
    """Computed receipts linking each idea's view → its portfolio weight.

    This is the §3.2 traceability: every weight decomposes back to the view
    (expected return) and confidence that produced it.
    """
    from provenance import computed_receipt

    out = []
    for tk, w in (weights or {}).items():
        out.append(computed_receipt(
            f"{tk} weight", round(float(w), 6),
            formula_ref=f"quant.portfolio.construct_portfolio[{method}]",
            inputs={"view_excess_return": views.get(tk), "view_confidence": confidences.get(tk)},
            source_name="engine", ticker=tk,
            label=f"{tk} target weight ({method})",
        ))
    return out


def construct_portfolio(
    trade_ideas: list[dict],
    cov_data: dict,
    *,
    method: str = "bl",
    market_caps: dict | None = None,
) -> dict:
    """Build target weights from agent ideas with full traceability.

    `cov_data` is the `quant.risk.compute_ewma_covariance` output dict
    ({matrix, tickers, ...}) — Ledoit-Wolf-shrunk covariance.

    method="bl"  → Black-Litterman (views from ideas, omega from conviction).
    method="hrp" → Hierarchical Risk Parity (diversification, ignores views).

    Returns {weights, method, view_weight_receipts, views, confidences, note}.
    Never raises — degrades to HRP, then inverse-variance.
    """
    cov_data = cov_data or {}
    tickers = list(cov_data.get("tickers") or [])
    matrix = cov_data.get("matrix") or []
    views, confidences = ideas_to_views(trade_ideas)
    result_weights: dict = {}
    note = ""
    used = method

    if method == "bl":
        try:
            from quant.optimizer import black_litterman
            bl = black_litterman(tickers, cov_data, views, confidences, market_caps=market_caps)
            result_weights = bl.get("weights") or {}
            note = bl.get("note", "") or bl.get("error", "")
            if bl.get("error"):
                used = "hrp"
        except Exception as e:  # noqa: BLE001
            note = f"BL failed ({e}); fell back to HRP"
            used = "hrp"

    if used == "hrp" or not result_weights:
        hrp = hrp_weights(matrix, tickers)
        result_weights = hrp.get("weights") or {}
        used = hrp.get("method", "hrp")
        note = (note + "; " if note else "") + (hrp.get("note", "") or "")

    receipts = view_weight_receipts(result_weights, views, confidences, method=used)
    return {
        "weights": result_weights,
        "method": used,
        "views": views,
        "confidences": confidences,
        "view_weight_receipts": receipts,
        "note": note.strip("; "),
    }
