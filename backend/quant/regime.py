"""
Regime Detection — HMM-based macro regime classification.

Uses Hidden Markov Model on FRED data (VIX, credit spreads, yield curve)
to classify the market into probabilistic regime states.
Pure math — zero LLM calls, reproducible, auditable.
"""

import numpy as np
from sklearn.preprocessing import StandardScaler
import logging
import time

logger = logging.getLogger(__name__)

# Try to import hmmlearn — graceful fallback if not installed
try:
    from hmmlearn.hmm import GaussianHMM
    HMM_AVAILABLE = True
except ImportError:
    HMM_AVAILABLE = False
    logger.warning("hmmlearn not installed — regime detection will use rule-based fallback")


REGIME_LABELS = {0: "risk_on", 1: "risk_off", 2: "transition"}

# Cache fitted model
_fitted_model = None
_fitted_scaler = None
_fit_timestamp = 0
_FIT_TTL = 86400  # Refit daily


def _rule_based_regime(vix: float, credit_spread: float, yield_curve: float) -> dict:
    """Simple rule-based fallback when HMM isn't available."""
    if vix < 18 and credit_spread < 3.5 and yield_curve > 0:
        regime = "risk_on"
        probs = {"risk_on": 0.75, "risk_off": 0.10, "transition": 0.15}
    elif vix > 28 or credit_spread > 5 or yield_curve < -0.2:
        regime = "risk_off"
        probs = {"risk_on": 0.10, "risk_off": 0.75, "transition": 0.15}
    else:
        regime = "transition"
        probs = {"risk_on": 0.30, "risk_off": 0.30, "transition": 0.40}

    return {
        "current_regime": regime,
        "probabilities": probs,
        "method": "rule_based",
        "confidence": max(probs.values()),
    }


def fit_regime_model(macro_history: list[dict]) -> bool:
    """
    Fit HMM on historical macro data.
    macro_history = [{date, vix, credit_spread, yield_curve}, ...]
    Returns True if fitting succeeded.
    """
    global _fitted_model, _fitted_scaler, _fit_timestamp

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

        scaler = StandardScaler()
        X = scaler.fit_transform(features)

        model = GaussianHMM(
            n_components=3,
            covariance_type="full",
            n_iter=100,
            random_state=42,
        )
        model.fit(X)

        # Label regimes by VIX mean: lowest VIX = risk_on, highest = risk_off
        means = model.means_
        vix_means = means[:, 0]  # First feature is VIX (scaled)
        sorted_indices = np.argsort(vix_means)
        # Remap: lowest VIX cluster = risk_on, highest = risk_off
        global REGIME_LABELS
        REGIME_LABELS = {
            sorted_indices[0]: "risk_on",
            sorted_indices[1]: "transition",
            sorted_indices[2]: "risk_off",
        }

        _fitted_model = model
        _fitted_scaler = scaler
        _fit_timestamp = time.time()
        logger.info("HMM regime model fitted successfully")
        return True
    except Exception as e:
        logger.error(f"HMM fitting failed: {e}")
        return False


def classify_regime(vix: float, credit_spread: float, yield_curve: float) -> dict:
    """
    Classify current regime using fitted HMM or rule-based fallback.
    Returns regime label, probabilities, and confidence.
    """
    global _fitted_model, _fitted_scaler

    if not _fitted_model or not _fitted_scaler:
        return _rule_based_regime(vix, credit_spread, yield_curve)

    try:
        X = _fitted_scaler.transform([[vix, credit_spread, yield_curve]])
        state = int(_fitted_model.predict(X)[0])
        probs = _fitted_model.predict_proba(X)[0]

        regime = REGIME_LABELS.get(state, "transition")
        prob_dict = {REGIME_LABELS.get(i, f"state_{i}"): round(float(p), 3) for i, p in enumerate(probs)}

        # Transition matrix
        trans = _fitted_model.transmat_
        trans_list = [[round(float(trans[i, j]), 3) for j in range(3)] for i in range(3)]

        return {
            "current_regime": regime,
            "probabilities": prob_dict,
            "transition_matrix": trans_list,
            "method": "hmm",
            "confidence": round(float(max(probs)), 3),
        }
    except Exception as e:
        logger.warning(f"HMM prediction failed, using rule-based: {e}")
        return _rule_based_regime(vix, credit_spread, yield_curve)


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
            regime = REGIME_LABELS.get(int(states[i]), "transition")
            prob_dict = {REGIME_LABELS.get(j, f"s{j}"): round(float(probs[i, j]), 3) for j in range(3)}
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
