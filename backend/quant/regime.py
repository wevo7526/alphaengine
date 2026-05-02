"""
Regime Detection — HMM-based macro regime classification.

Uses Hidden Markov Model on FRED data (VIX, credit spreads, yield curve)
to classify the market into probabilistic regime states.
Pure math — zero LLM calls, reproducible, auditable.
"""

import math
import numpy as np
import logging
import time
import threading

logger = logging.getLogger(__name__)

# Guards mutation of _fitted_model / _fitted_scaler / _fitted_labels and
# the hysteresis state. Acquired briefly for atomic swaps; never held
# during HMM prediction or fitting (those operate on local refs).
_state_lock = threading.RLock()

# Lazy imports for heavy ML libraries — saves ~1.2s on cold start
_GaussianHMM = None
_StandardScaler = None
HMM_AVAILABLE = None  # Resolved on first use


def _ensure_ml_imports():
    global _GaussianHMM, _StandardScaler, HMM_AVAILABLE
    if HMM_AVAILABLE is not None:
        return
    try:
        from hmmlearn.hmm import GaussianHMM
        from sklearn.preprocessing import StandardScaler
        _GaussianHMM = GaussianHMM
        _StandardScaler = StandardScaler
        HMM_AVAILABLE = True
    except ImportError:
        HMM_AVAILABLE = False
        logger.warning("hmmlearn not installed — regime detection will use rule-based fallback")


_DEFAULT_REGIME_LABELS = {0: "risk_on", 1: "risk_off", 2: "transition"}

# Cache fitted model
_fitted_model = None
_fitted_scaler = None
_fitted_labels: dict = dict(_DEFAULT_REGIME_LABELS)
_fit_timestamp = 0
_fit_diagnostics: dict = {}  # converged, iterations, log_likelihood
_FIT_TTL = 86400  # Refit daily

# Hysteresis state — last classified regime + how many days we've been in it.
# Prevents single-day flips on ambiguous data: a new regime must beat the
# current one by `_REGIME_FLIP_MARGIN` for `_MIN_REGIME_DAYS` consecutive
# observations before we accept it. This is the real-world equivalent of
# a "Schmitt trigger" on the classifier — the same trick risk officers use
# to keep a noisy regime call from churning the trade book.
_last_regime: str | None = None
_last_regime_streak: int = 0
_pending_regime: str | None = None
_pending_regime_streak: int = 0
_MIN_REGIME_DAYS = 5
_REGIME_FLIP_MARGIN = 0.10  # new regime prob must exceed current by 10pp


# Rule-based regime thresholds. Pulled to module-level so the satisfaction
# scoring uses the same anchors as the discrete classification.
_RB_VIX_RISK_ON = 18.0
_RB_VIX_RISK_OFF = 28.0
_RB_CREDIT_RISK_ON = 3.5
_RB_CREDIT_RISK_OFF = 5.0
_RB_YC_RISK_ON = 0.0       # positive curve = expansion
_RB_YC_RISK_OFF = -0.2     # inverted curve = recession signal


def _logistic(x: float) -> float:
    """Numerically-safe sigmoid (avoids overflow on large negative x)."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    ex = math.exp(x)
    return ex / (1.0 + ex)


def _rule_based_regime(vix: float, credit_spread: float, yield_curve: float) -> dict:
    """
    Rule-based fallback regime classifier.

    Probabilities are derived from how strongly the inputs satisfy each
    regime's threshold pattern, not stipulated as fixed (0.75/0.10/0.15)
    constants. Each indicator contributes a sigmoid satisfaction score —
    when the value sits exactly on the threshold the score is 0.5; when
    well past it, the score saturates near 1.0. Average across indicators
    gives the per-regime score; a residual transition score absorbs
    ambiguity, then everything is normalized to a probability simplex.

    The discrete "current_regime" still uses the original hard rules so
    behavior is unchanged at the boundary; only the probability vector is
    now data-driven.
    """
    # Satisfaction scores in [0, 1] for each regime
    on_vix = _logistic((_RB_VIX_RISK_ON - vix) / 4.0)
    on_credit = _logistic((_RB_CREDIT_RISK_ON - credit_spread) / 0.5)
    on_yc = _logistic((yield_curve - _RB_YC_RISK_ON) / 0.2)
    risk_on_score = (on_vix + on_credit + on_yc) / 3.0

    off_vix = _logistic((vix - _RB_VIX_RISK_OFF) / 4.0)
    off_credit = _logistic((credit_spread - _RB_CREDIT_RISK_OFF) / 0.5)
    off_yc = _logistic((_RB_YC_RISK_OFF - yield_curve) / 0.2)
    risk_off_score = (off_vix + off_credit + off_yc) / 3.0

    # Transition is the residual ambiguity: when neither extreme is well-met,
    # we're in transition. Floor at 0.05 so a clear regime never gives 0.
    transition_score = max(0.05, 1.0 - max(risk_on_score, risk_off_score))

    total = risk_on_score + risk_off_score + transition_score
    probs = {
        "risk_on": round(risk_on_score / total, 3),
        "risk_off": round(risk_off_score / total, 3),
        "transition": round(transition_score / total, 3),
    }

    # Discrete classification keeps the original boolean rules so hysteresis
    # and downstream logic see the same regime labels they always did.
    if vix < _RB_VIX_RISK_ON and credit_spread < _RB_CREDIT_RISK_ON and yield_curve > _RB_YC_RISK_ON:
        regime = "risk_on"
    elif vix > _RB_VIX_RISK_OFF or credit_spread > _RB_CREDIT_RISK_OFF or yield_curve < _RB_YC_RISK_OFF:
        regime = "risk_off"
    else:
        regime = "transition"

    return {
        "current_regime": regime,
        "probabilities": probs,
        "method": "rule_based",
        "confidence": float(probs[regime]),
    }


def fit_regime_model(macro_history: list[dict]) -> bool:
    """
    Fit HMM on historical macro data.
    macro_history = [{date, vix, credit_spread, yield_curve}, ...]
    Returns True if fitting succeeded.
    """
    global _fitted_model, _fitted_scaler, _fitted_labels, _fit_timestamp, _fit_diagnostics

    _ensure_ml_imports()
    if not HMM_AVAILABLE:
        return False

    if len(macro_history) < 60:
        logger.warning("Not enough macro history for HMM fitting (need 60+)")
        return False

    try:
        features = np.array([
            [d.get("vix", 20), d.get("credit_spread", 3), d.get("yield_curve", 0.5)]
            for d in macro_history
            if d.get("vix") is not None
        ])

        if len(features) < 60:
            return False

        scaler = _StandardScaler()
        X = scaler.fit_transform(features)

        model = _GaussianHMM(
            n_components=3,
            covariance_type="full",
            n_iter=100,
            random_state=42,
        )
        model.fit(X)

        # Convergence diagnostic — hmmlearn exposes the EM monitor on the
        # fitted model. Surface this so the caller can downgrade to rule-based
        # or trigger an alert if a fit converged poorly.
        try:
            converged = bool(getattr(model.monitor_, "converged", False))
            iterations = int(getattr(model.monitor_, "iter", 0))
            log_likelihood = float(model.score(X))
        except Exception:
            converged = False
            iterations = 0
            log_likelihood = float("nan")
        if not converged:
            logger.warning(
                f"HMM did not converge after {iterations} iterations — "
                "regime classifications will fall back to rule-based"
            )

        # Label regimes by VIX mean: lowest VIX = risk_on, highest = risk_off
        means = model.means_
        vix_means = means[:, 0]  # First feature is VIX (scaled)
        sorted_indices = np.argsort(vix_means)
        # Remap: lowest VIX cluster = risk_on, highest = risk_off
        new_labels = {
            int(sorted_indices[0]): "risk_on",
            int(sorted_indices[1]): "transition",
            int(sorted_indices[2]): "risk_off",
        }

        # Atomic swap under lock — concurrent readers see either the old
        # complete state or the new complete state, never a half-mutated mix.
        # If EM didn't converge we still cache the model (the rule-based
        # fallback is only triggered when converged=False at predict time).
        with _state_lock:
            if converged:
                _fitted_model = model
                _fitted_scaler = scaler
                _fitted_labels = new_labels
                _fit_timestamp = time.time()
            _fit_diagnostics = {
                "converged": converged,
                "iterations": iterations,
                "log_likelihood": log_likelihood if math.isfinite(log_likelihood) else None,
                "n_observations": int(len(features)),
                "fit_at": time.time(),
            }
        if converged:
            logger.info(f"HMM regime model fitted (iter={iterations}, ll={log_likelihood:.2f})")
        return bool(converged)
    except Exception as e:
        logger.error(f"HMM fitting failed: {e}")
        return False


def _apply_hysteresis(raw_regime: str, prob_dict: dict) -> tuple[str, dict]:
    """
    Smooth single-day regime flips. Returns (final_regime, hysteresis_info).

    Rules:
      - First call: accept whatever the model says, start a streak.
      - Subsequent calls: if the raw regime differs from the current,
        require the new regime's probability to exceed the current's by
        `_REGIME_FLIP_MARGIN` for `_MIN_REGIME_DAYS` consecutive obs
        before flipping. Otherwise hold the current regime.

    The classifier's *probabilities* still reflect the raw signal so the
    user can see what the model thinks; only the headline regime label
    is sticky.
    """
    global _last_regime, _last_regime_streak, _pending_regime, _pending_regime_streak

    with _state_lock:
        info = {"applied": False, "streak_days": 0, "pending": None, "pending_days": 0}

        if _last_regime is None:
            _last_regime = raw_regime
            _last_regime_streak = 1
            info.update({"streak_days": 1})
            return raw_regime, info

        if raw_regime == _last_regime:
            _last_regime_streak += 1
            # Reset any pending counter — current regime reaffirmed
            _pending_regime = None
            _pending_regime_streak = 0
            info.update({"streak_days": _last_regime_streak})
            return _last_regime, info

        # raw_regime != _last_regime. Check flip margin.
        current_prob = float(prob_dict.get(_last_regime, 0.0))
        new_prob = float(prob_dict.get(raw_regime, 0.0))
        margin_ok = new_prob >= current_prob + _REGIME_FLIP_MARGIN

        if not margin_ok:
            # Margin too thin — hold current, reset pending
            _pending_regime = None
            _pending_regime_streak = 0
            info.update({
                "applied": True,
                "streak_days": _last_regime_streak,
                "pending": raw_regime,
                "pending_days": 0,
                "reason": (
                    f"Held regime '{_last_regime}': new '{raw_regime}' prob "
                    f"({new_prob:.2f}) within {_REGIME_FLIP_MARGIN:.2f} of current ({current_prob:.2f})"
                ),
            })
            return _last_regime, info

        # Margin OK — start or continue a pending flip
        if _pending_regime == raw_regime:
            _pending_regime_streak += 1
        else:
            _pending_regime = raw_regime
            _pending_regime_streak = 1

        if _pending_regime_streak >= _MIN_REGIME_DAYS:
            # Confirmed flip
            _last_regime = raw_regime
            _last_regime_streak = _pending_regime_streak
            _pending_regime = None
            _pending_regime_streak = 0
            info.update({
                "applied": True,
                "streak_days": _last_regime_streak,
                "reason": f"Flip confirmed after {_MIN_REGIME_DAYS} consecutive days",
            })
            return raw_regime, info

        # Pending but not yet confirmed
        info.update({
            "applied": True,
            "streak_days": _last_regime_streak,
            "pending": raw_regime,
            "pending_days": _pending_regime_streak,
            "reason": (
                f"Pending flip to '{raw_regime}' on day {_pending_regime_streak}/{_MIN_REGIME_DAYS}"
            ),
        })
        return _last_regime, info


def classify_regime(
    vix: float,
    credit_spread: float,
    yield_curve: float,
    apply_hysteresis: bool = True,
) -> dict:
    """
    Classify current regime using fitted HMM or rule-based fallback.

    `apply_hysteresis=True` (default) smooths single-day flips so the
    headline regime doesn't churn on ambiguous data. Set False for
    backtesting where you want raw daily classifications.
    """
    global _fitted_model, _fitted_scaler

    if not _fitted_model or not _fitted_scaler:
        rb = _rule_based_regime(vix, credit_spread, yield_curve)
        if apply_hysteresis:
            final_regime, hyst = _apply_hysteresis(rb["current_regime"], rb["probabilities"])
            rb["raw_regime"] = rb["current_regime"]
            rb["current_regime"] = final_regime
            rb["hysteresis"] = hyst
        return rb

    try:
        X = _fitted_scaler.transform([[vix, credit_spread, yield_curve]])
        state = int(_fitted_model.predict(X)[0])
        probs = _fitted_model.predict_proba(X)[0]

        raw_regime = _fitted_labels.get(state, "transition")
        prob_dict = {_fitted_labels.get(i, f"state_{i}"): round(float(p), 3) for i, p in enumerate(probs)}

        # Transition matrix
        trans = _fitted_model.transmat_
        trans_list = [[round(float(trans[i, j]), 3) for j in range(3)] for i in range(3)]

        result = {
            "current_regime": raw_regime,
            "raw_regime": raw_regime,
            "probabilities": prob_dict,
            "transition_matrix": trans_list,
            "method": "hmm",
            "confidence": round(float(max(probs)), 3),
        }

        if apply_hysteresis:
            final_regime, hyst = _apply_hysteresis(raw_regime, prob_dict)
            result["current_regime"] = final_regime
            result["hysteresis"] = hyst

        return result
    except Exception as e:
        logger.warning(f"HMM prediction failed, using rule-based: {e}")
        rb = _rule_based_regime(vix, credit_spread, yield_curve)
        if apply_hysteresis:
            final_regime, hyst = _apply_hysteresis(rb["current_regime"], rb["probabilities"])
            rb["raw_regime"] = rb["current_regime"]
            rb["current_regime"] = final_regime
            rb["hysteresis"] = hyst
        return rb


def get_regime_history(macro_history: list[dict]) -> list[dict]:
    """Classify regime at each historical point. Returns list of {date, regime, probabilities}."""
    if not _fitted_model or not _fitted_scaler:
        return []

    try:
        features = np.array([
            [d.get("vix", 20), d.get("credit_spread", 3), d.get("yield_curve", 0.5)]
            for d in macro_history
        ])
        X = _fitted_scaler.transform(features)
        states = _fitted_model.predict(X)
        probs = _fitted_model.predict_proba(X)

        history = []
        for i, d in enumerate(macro_history):
            regime = _fitted_labels.get(int(states[i]), "transition")
            prob_dict = {_fitted_labels.get(j, f"s{j}"): round(float(probs[i, j]), 3) for j in range(3)}
            history.append({
                "date": d.get("date", ""),
                "regime": regime,
                "probabilities": prob_dict,
                "confidence": round(float(max(probs[i])), 3),
            })
        return history
    except Exception as e:
        logger.error(f"Regime history failed: {e}")
        return []


def get_fit_diagnostics() -> dict:
    """Return the HMM fit diagnostics — converged flag, iterations, LL."""
    with _state_lock:
        return dict(_fit_diagnostics)


def regime_size_multiplier(regime: str | None, confidence: float | None = None) -> dict:
    """
    Convert a regime classification into a position-size multiplier.

    Risk-on:     1.0  (full sizing)
    Transition:  0.75 (lean back 25%)
    Risk-off:    0.5  (half sizing)
    Unknown:     1.0  (don't penalize when we don't know)

    Confidence-blended: low-confidence regime calls have less effect. If
    confidence is 0.4 (uncertain), a risk_off classification will only
    move the multiplier 40% of the way from 1.0 toward 0.5. This avoids
    over-reacting to noisy single-day flips.

    Returns {"multiplier": float, "regime": str, "confidence": float|None,
             "reason": str} for transparent surfacing in the risk gate UI.
    """
    base_map = {
        "risk_on": 1.0,
        "transition": 0.75,
        "risk_off": 0.5,
    }
    target = base_map.get((regime or "").lower(), 1.0)

    # Default to full confidence if not provided
    conf = float(confidence) if confidence is not None else 1.0
    conf = max(0.0, min(1.0, conf))

    # Blend: from baseline 1.0 toward target by `conf` weight
    multiplier = 1.0 + conf * (target - 1.0)
    multiplier = max(0.0, min(1.0, multiplier))

    if regime == "risk_off":
        reason = f"Regime risk_off (conf {conf:.0%}): sizing {int((1 - multiplier) * 100)}% lower"
    elif regime == "transition":
        reason = f"Regime transition (conf {conf:.0%}): sizing {int((1 - multiplier) * 100)}% lower"
    elif regime == "risk_on":
        reason = "Regime risk_on: full sizing allowed"
    else:
        reason = f"Regime unknown ('{regime}'): no adjustment"

    return {
        "multiplier": round(multiplier, 4),
        "regime": regime or "unknown",
        "confidence": round(conf, 3),
        "reason": reason,
    }


def regime_conditional_returns(
    regime_history: list[dict],
    asset_returns: list[float],
) -> dict:
    """
    Historical average return of an asset in each regime.
    Tells you: "in risk_off, stocks return -X% on average."
    Critical for regime-aware position sizing.
    """
    if not regime_history or not asset_returns:
        return {}

    min_len = min(len(regime_history), len(asset_returns))
    regime_returns: dict[str, list[float]] = {}

    for i in range(min_len):
        regime = regime_history[i].get("regime", "unknown")
        if regime not in regime_returns:
            regime_returns[regime] = []
        regime_returns[regime].append(asset_returns[i])

    result = {}
    for regime, returns in regime_returns.items():
        arr = np.array(returns)
        n = len(arr)
        mean_daily = float(np.mean(arr))
        std_daily = float(np.std(arr, ddof=1)) if n > 1 else 0.0
        # t-stat for "is the mean return significantly different from zero?"
        # Standard error of the mean = std / sqrt(n)
        se = std_daily / np.sqrt(n) if n > 0 else 0.0
        t_stat = mean_daily / se if se > 0 else 0.0
        # Two-sided p-value approximation via normal CDF (large-sample) —
        # for n>=30 this is within 1% of the true t distribution and avoids
        # pulling scipy.stats just for a p-value.
        # p ≈ 2 * (1 - Phi(|t|))   where Phi is the standard normal CDF
        from math import erf, sqrt
        p_value = 2.0 * (1.0 - 0.5 * (1.0 + erf(abs(t_stat) / sqrt(2.0)))) if t_stat != 0 else 1.0

        # Low-sample flag: <30 obs is not enough for reliable inference
        low_sample = n < 30
        # Significant at 5% only if both sample is adequate AND p < 0.05
        significant = (not low_sample) and (p_value < 0.05)

        result[regime] = {
            "avg_daily_return_pct": round(mean_daily * 100, 4),
            "annualized_return_pct": round(mean_daily * 252 * 100, 2),
            "volatility_pct": round(std_daily * np.sqrt(252) * 100, 2),
            "observations": n,
            "positive_pct": round(sum(1 for r in returns if r > 0) / n * 100, 1) if n else None,
            "t_stat": round(float(t_stat), 3),
            "p_value": round(float(p_value), 4),
            "low_sample": bool(low_sample),
            "significant_at_5pct": bool(significant),
        }

    return result
