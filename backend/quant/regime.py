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


# 4-state taxonomy, ordered by stress score (low → high):
#   risk_on     — VIX low, credit tight, curve steep
#   late_cycle  — VIX low-mid, credit modest, curve flattening
#   transition  — VIX mid-high, credit widening, curve flat/slightly inverted
#   risk_off    — VIX high, credit wide, curve deeply inverted or recovering
# The 4-state design gives the HMM enough room to avoid one state hogging
# probability mass (the 3-state collapse was the root cause of the
# degenerate 100% posterior). Late_cycle especially captures the
# "still ok but cracks showing" macro picture that the 3-state model
# was forcing into either transition or risk_on.
_DEFAULT_REGIME_LABELS = {0: "risk_on", 1: "late_cycle", 2: "transition", 3: "risk_off"}

# Size multiplier per regime — applied by the trade gate.
# late_cycle sits between risk_on (1.0) and transition (0.75): the book is
# still functional but we lean back a notch because curve flattening is
# the canonical signal that a turn is being priced.
_REGIME_SIZE_MULTIPLIERS = {
    "risk_on": 1.0,
    "late_cycle": 0.85,
    "transition": 0.75,
    "risk_off": 0.5,
}

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
_MIN_REGIME_DAYS = 10        # was 5 — bumped because the underlying classifier
_REGIME_FLIP_MARGIN = 0.15   #   was switching too often; now needs 10 days
                             #   of 15pp dominance to flip the headline regime.


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


def _smooth_posterior(probs, temperature: float = 2.0, prior_weight: float = 0.10):
    """Calibrate an HMM posterior so it reads as a meaningful probability.

    Two operations, in this order:
      1. Mix with a uniform prior: p' = (1 - w) * p + w * uniform(n)
         This is the fix for the degenerate "1.0 / 0.0 / 0.0" posteriors
         hmmlearn produces when one Gaussian density dwarfs the others
         on a single observation. Even with diagonal covariance, an
         outlier observation can still produce a near-degenerate
         posterior — the mix-with-prior guarantees a floor.
      2. Temperature scaling: log_p / T, renormalized. T > 1 flattens,
         T < 1 sharpens, T = 1 is a no-op (just a smoothing). Reflects
         genuine macro ambiguity that the model alone underestimates.

    With defaults (w=0.10, T=2.0) a raw 1.0/0.0/0.0 posterior becomes
    roughly 0.85/0.075/0.075 — reads as "very confident" without
    claiming impossible certainty. A raw 0.5/0.3/0.2 becomes ~0.43/
    0.34/0.23, which is what we want — "leaning, but ambiguous".
    """
    arr = np.asarray(probs, dtype=float)
    if arr.size == 0:
        return arr
    n = arr.size
    # Step 1 — mix with uniform prior. Guarantees a strict positive
    # floor on every state, killing the degenerate 100% posterior.
    arr = (1.0 - prior_weight) * arr + prior_weight / n
    # Step 2 — temperature scaling for additional calibration.
    arr = np.clip(arr, 1e-12, 1.0)
    log_p = np.log(arr) / float(temperature)
    log_p -= log_p.max()
    exp = np.exp(log_p)
    return exp / exp.sum()


def _bell(x: float, center: float, width: float) -> float:
    """Bell-shape satisfaction score in (0, 1] centered at `center`."""
    return math.exp(-((x - center) ** 2) / (2.0 * width * width))


def _rule_based_regime(vix: float, credit_spread: float, yield_curve: float) -> dict:
    """4-state rule-based fallback regime classifier.

    Each regime gets a continuous satisfaction score derived from sigmoid
    or bell-shape kernels on the three macro inputs. Scores are then
    normalized to a probability simplex with a small floor so no state
    is ever exactly 0.

    The discrete `current_regime` is argmax of the simplex — cleaner
    and self-consistent vs. the old hard-rule branch.
    """
    # risk_on — all three indicators in the "easy" zone
    on_vix = _logistic((_RB_VIX_RISK_ON - vix) / 4.0)
    on_credit = _logistic((_RB_CREDIT_RISK_ON - credit_spread) / 0.5)
    on_yc = _logistic((yield_curve - _RB_YC_RISK_ON) / 0.2)
    risk_on_score = (on_vix + on_credit + on_yc) / 3.0

    # risk_off — extreme stress
    off_vix = _logistic((vix - _RB_VIX_RISK_OFF) / 4.0)
    off_credit = _logistic((credit_spread - _RB_CREDIT_RISK_OFF) / 0.5)
    off_yc = _logistic((_RB_YC_RISK_OFF - yield_curve) / 0.2)
    risk_off_score = (off_vix + off_credit + off_yc) / 3.0

    # late_cycle — modest VIX (18-23), modest credit (3-5), curve flattening
    # (yc < 0.5). Bell shapes peak in the middle of each band; the curve
    # term is a sigmoid so a deeply inverted curve also reads as "late"
    # rather than only "transition".
    late_vix = _bell(vix, 20.0, 4.0)
    late_credit = _bell(credit_spread, 4.0, 1.0)
    late_yc = _logistic((0.5 - yield_curve) / 0.3)
    late_cycle_score = (late_vix + late_credit + late_yc) / 3.0

    # transition — residual ambiguity. Floor at 0.05 so it never zeroes.
    transition_score = max(
        0.05,
        1.0 - max(risk_on_score, risk_off_score, late_cycle_score),
    )

    total = risk_on_score + risk_off_score + late_cycle_score + transition_score
    probs = {
        "risk_on": round(risk_on_score / total, 3),
        "late_cycle": round(late_cycle_score / total, 3),
        "transition": round(transition_score / total, 3),
        "risk_off": round(risk_off_score / total, 3),
    }
    regime = max(probs, key=probs.get)

    return {
        "current_regime": regime,
        "probabilities": probs,
        "method": "rule_based",
        "confidence": float(probs[regime]),
    }


def fit_regime_model(macro_history: list[dict], force: bool = False) -> bool:
    """
    Fit HMM on historical macro data.
    macro_history = [{date, vix, credit_spread, yield_curve}, ...]

    Honors `_FIT_TTL` — if a fit completed within the last 24h, this
    is a no-op (returns True so callers don't fall back to rule-based).
    Pass `force=True` to refit unconditionally (e.g., from a cron after
    a known regime event). The old code refit on every API call, which
    caused (a) latency, (b) label permutations between fits with
    numerically-close cluster means, manifesting as apparent regime
    switching.

    Also switched `covariance_type` from "full" to "diag" — with 3
    features × 3 states and ~500 highly-autocorrelated daily obs, full
    covariance over-fits, produces near-singular covariance matrices,
    and collapses the posterior to 1.0/0.0/0.0. Diagonal covariance
    is the standard fix for low-effective-N HMMs and dramatically
    improves the posterior calibration.

    Returns True if a usable fit exists (cached or newly produced).
    """
    global _fitted_model, _fitted_scaler, _fitted_labels, _fit_timestamp, _fit_diagnostics

    _ensure_ml_imports()
    if not HMM_AVAILABLE:
        return False

    # Honor the TTL — cheap path when the model is still warm.
    if not force and _fitted_model is not None:
        age = time.time() - _fit_timestamp
        if age < _FIT_TTL:
            return True

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

        # 4 states + diagonal covariance + min_covar floor. Going from 3
        # → 4 components gives the EM enough room that no single state
        # has to hog probability mass; combined with the diag covariance
        # this eliminates the degenerate posterior at the source.
        model = _GaussianHMM(
            n_components=4,
            covariance_type="diag",
            n_iter=100,
            tol=1e-3,
            min_covar=1e-3,
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

        # Label regimes by a composite stress score:
        #   stress = mean_VIX + mean_credit_spread − mean_yield_curve
        # (all in scaler-normalized units). Sorting by this composite
        # incorporates all three features so labels stay stable across
        # refits even when two clusters have numerically-close VIX means.
        # Lowest stress → risk_on; highest → risk_off; in between →
        # late_cycle then transition.
        means = model.means_
        stress_score = means[:, 0] + means[:, 1] - means[:, 2]
        sorted_indices = np.argsort(stress_score)
        new_labels = {
            int(sorted_indices[0]): "risk_on",
            int(sorted_indices[1]): "late_cycle",
            int(sorted_indices[2]): "transition",
            int(sorted_indices[3]): "risk_off",
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
    macro_window: list[dict] | None = None,
    apply_hysteresis: bool = True,
) -> dict:
    """Classify current regime using fitted HMM or rule-based fallback.

    Args
    ----
    vix, credit_spread, yield_curve
        Today's macro values. Used directly by the rule-based fallback;
        passed alongside `macro_window` to the HMM so the last point in
        the window is consistent with today's reading.

    macro_window
        Recent macro observations [{vix, credit_spread, yield_curve}, ...]
        ordered oldest → newest. When provided, the HMM runs
        `predict_proba` over the full window and takes the LAST row
        (which is the proper Bayesian filtered posterior at time T —
        the smoothed and filtered distributions are identical for the
        endpoint of an observation sequence). This eliminates the
        "single observation produces extreme posterior" failure mode
        because the transition matrix anchors today's posterior to
        yesterday's belief.

        When NOT provided (legacy callers), the function falls back to
        the old single-point prediction. The smoothing layer still
        floors any state at non-zero, so the worst case isn't degenerate
        any more — just less informed.

    apply_hysteresis
        `True` (default) smooths single-day flips so the headline regime
        doesn't churn. Underlying probabilities still update daily.
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
        n_components = _fitted_model.n_components
        # Build the input sequence: window if provided, else single point.
        if macro_window and len(macro_window) >= 2:
            # Take up to the last 60 observations (~3 trading months).
            # Long enough for the transition matrix to matter, short
            # enough that the posterior reflects the current regime
            # rather than dragging in old context.
            recent = [
                [d.get("vix", vix), d.get("credit_spread", credit_spread),
                 d.get("yield_curve", yield_curve)]
                for d in macro_window[-60:]
                if d.get("vix") is not None
            ]
            # Ensure today's values are the final row so the filtered
            # posterior anchors to the latest reading.
            recent.append([vix, credit_spread, yield_curve])
            X = _fitted_scaler.transform(np.array(recent))
            all_probs = _fitted_model.predict_proba(X)
            raw_probs = all_probs[-1]
            # State at T is argmax of the filtered posterior, not the
            # Viterbi-decoded sequence — consistent with how we report
            # probabilities.
            state = int(np.argmax(raw_probs))
            posterior_method = "forward_filtered"
        else:
            X = _fitted_scaler.transform([[vix, credit_spread, yield_curve]])
            state = int(_fitted_model.predict(X)[0])
            raw_probs = _fitted_model.predict_proba(X)[0]
            posterior_method = "single_point"

        # Smooth: mix with uniform prior (kills any residual degeneracy)
        # then temperature-scale to admit macro ambiguity the model
        # alone underestimates.
        probs = _smooth_posterior(raw_probs, temperature=2.0)

        raw_regime = _fitted_labels.get(state, "transition")
        prob_dict = {
            _fitted_labels.get(i, f"state_{i}"): round(float(p), 3)
            for i, p in enumerate(probs)
        }

        # Transition matrix — full size, no longer hard-coded to 3×3.
        trans = _fitted_model.transmat_
        trans_list = [
            [round(float(trans[i, j]), 3) for j in range(n_components)]
            for i in range(n_components)
        ]

        result = {
            "current_regime": raw_regime,
            "raw_regime": raw_regime,
            "probabilities": prob_dict,
            "transition_matrix": trans_list,
            "method": "hmm",
            "posterior_method": posterior_method,
            "confidence": round(float(max(probs)), 3),
            "n_states": int(n_components),
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

        n_components = _fitted_model.n_components
        history = []
        for i, d in enumerate(macro_history):
            regime = _fitted_labels.get(int(states[i]), "transition")
            # Apply same temperature smoothing as predict-time so the
            # historical confidence trace matches what /api/quant/regime
            # surfaces for "today". Loop bounds use the model's actual
            # n_components so we're robust to the 3 → 4 state change.
            smoothed = _smooth_posterior(probs[i], temperature=2.0)
            prob_dict = {
                _fitted_labels.get(j, f"s{j}"): round(float(smoothed[j]), 3)
                for j in range(n_components)
            }
            history.append({
                "date": d.get("date", ""),
                "regime": regime,
                "probabilities": prob_dict,
                "confidence": round(float(max(smoothed)), 3),
            })
        return history
    except Exception as e:
        logger.error(f"Regime history failed: {e}")
        return []


def get_fit_diagnostics() -> dict:
    """Return the HMM fit diagnostics for the operations UI.

    Includes everything the frontend needs to assess fit quality:
      - converged, iterations, log_likelihood, n_observations
      - cached label mapping
      - time since fit + TTL
      - n_states + covariance_type for transparency
      - hysteresis state so we can show "X consecutive days in regime"
    """
    with _state_lock:
        diag = dict(_fit_diagnostics)
        diag["cached_label_mapping"] = dict(_fitted_labels)
        diag["model_present"] = _fitted_model is not None
        if _fitted_model is not None:
            diag["n_states"] = int(getattr(_fitted_model, "n_components", 0))
            diag["covariance_type"] = str(getattr(_fitted_model, "covariance_type", "unknown"))
        if _fit_timestamp > 0:
            diag["seconds_since_fit"] = round(time.time() - _fit_timestamp, 1)
            diag["ttl_seconds"] = _FIT_TTL
            diag["ttl_expires_in"] = round(max(0, _FIT_TTL - (time.time() - _fit_timestamp)), 1)
        diag["hysteresis"] = {
            "current_regime": _last_regime,
            "streak_days": _last_regime_streak,
            "pending_regime": _pending_regime,
            "pending_days": _pending_regime_streak,
            "min_regime_days": _MIN_REGIME_DAYS,
            "flip_margin": _REGIME_FLIP_MARGIN,
        }
        return diag


def regime_size_multiplier(regime: str | None, confidence: float | None = None) -> dict:
    """Convert a regime classification into a position-size multiplier.

    risk_on     → 1.00 (full)
    late_cycle  → 0.85 (gentle 15% trim; curve flattening is the canonical
                        "turn being priced" signal)
    transition  → 0.75 (lean back 25%)
    risk_off    → 0.50 (half)
    unknown     → 1.00 (don't penalize when we don't know)

    Confidence-blended: a low-confidence risk_off call only moves the
    multiplier `conf` of the way from 1.0 toward 0.5. Avoids over-reacting
    to noisy posteriors. With the new smoothed posterior the typical
    confidence is now ~0.4–0.7 rather than the old 0.95–1.0, so the
    multiplier reads as a calibrated dial rather than a hard switch.
    """
    target = _REGIME_SIZE_MULTIPLIERS.get((regime or "").lower(), 1.0)

    conf = float(confidence) if confidence is not None else 1.0
    conf = max(0.0, min(1.0, conf))

    multiplier = 1.0 + conf * (target - 1.0)
    multiplier = max(0.0, min(1.0, multiplier))

    trim_pct = int(round((1 - multiplier) * 100))
    if regime in ("risk_off", "transition", "late_cycle"):
        reason = f"Regime {regime} (conf {conf:.0%}): sizing {trim_pct}% lower"
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
