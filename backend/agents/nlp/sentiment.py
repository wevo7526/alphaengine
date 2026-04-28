"""
Lightweight financial sentiment analysis — pure Python, no native deps.

Built on vaderSentiment (rule-based, ~50KB) with a heavily-extended finance
lexicon covering equity research, macro, earnings, M&A, regulatory, and
options/derivatives language. Replaces the need for a heavyweight transformer
model (FinBERT) for a deployment-friendly, deterministic, sub-millisecond
scorer suitable for Railway's free tier.

Two-stage scoring:
  1. Pre-score multi-word financial phrases (e.g. "raised guidance",
     "missed estimates") via direct phrase matching, since VADER tokenizes
     by word and would lose the bigram/trigram signal.
  2. VADER on the rest with the finance-tuned unigram lexicon.

Aggregate score is the average compound, weighted by phrase length so a
single strong multi-word phrase outweighs many incidental neutral tokens.
"""

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import logging
import re

logger = logging.getLogger(__name__)


# === Single-word lexicon (added to VADER's unigrams) ===
_FINANCIAL_LEXICON: dict[str, float] = {
    # Direction
    "bullish": 2.5, "bearish": -2.5,
    "long": 0.6, "short": -0.6,
    "overweight": 1.5, "underweight": -1.5,

    # Ratings & analyst language
    "upgrade": 2.0, "downgrade": -2.0,
    "outperform": 1.8, "underperform": -1.8,
    "buy": 1.5, "sell": -1.5,
    "hold": 0.0, "neutral": 0.0,

    # Earnings & guidance
    "beat": 1.5, "beats": 1.5,
    "miss": -1.5, "misses": -1.5,
    "missed": -1.5, "beaten": 1.5,
    "exceeded": 1.5, "fell-short": -1.5,
    "guided": 0.3, "guidance": 0.3,
    "raised": 1.0, "lowered": -1.0,
    "reaffirmed": 0.5, "withdrew": -1.5,
    "preliminary": 0.0,

    # Price action
    "rally": 2.0, "surge": 2.0, "soar": 2.0, "jump": 1.5, "climb": 1.0,
    "selloff": -2.0, "plunge": -2.5, "tank": -2.0, "tumble": -1.8,
    "crash": -3.0, "collapse": -3.0, "rout": -2.5, "freefall": -3.0,
    "spike": 1.0, "skid": -1.5, "slide": -1.2,
    "rebound": 1.5, "recover": 1.0, "recovery": 1.5,
    "decline": -1.5, "drop": -1.0, "fall": -1.0, "sink": -1.5,
    "soaring": 2.0, "plummeting": -2.5,

    # Macro / cycle
    "recession": -2.5, "expansion": 1.5, "growth": 1.0, "contraction": -1.8,
    "inflation": -0.8, "deflation": -1.5, "stagflation": -2.5, "disinflation": 0.5,
    "boom": 1.8, "bust": -2.0, "downturn": -2.0, "uptrend": 1.5,
    "softening": -1.0, "strengthening": 1.0, "moderating": -0.3,
    "resilient": 1.2, "fragile": -1.5, "robust": 1.5,
    "stagnant": -1.2, "anemic": -1.5,

    # Fed / monetary
    "hawkish": -1.0, "dovish": 1.0,
    "tightening": -1.0, "easing": 1.0, "cuts": 0.8, "hikes": -0.8,
    "qe": 1.5, "qt": -1.5,
    "stimulus": 1.2,

    # Credit & financial health
    "default": -3.0, "defaulted": -3.0,
    "bankruptcy": -3.5, "chapter11": -3.5, "insolvency": -3.5,
    "restructuring": -1.0, "downgraded": -1.5, "upgraded": 1.5,
    "delinquent": -2.0, "delinquency": -2.0,
    "writedown": -2.0, "writeoff": -2.0, "writedowns": -2.0,
    "impairment": -1.8, "goodwill-impairment": -2.5,
    "covenant": -0.3, "breach": -2.0, "breached": -2.0,

    # Capital actions
    "dividend": 1.0, "dividends": 1.0,
    "buyback": 1.5, "buybacks": 1.5, "repurchase": 1.2,
    "ipo": 0.8, "spinoff": 0.5, "spin-off": 0.5,
    "secondary": -0.5, "dilution": -1.5, "dilutive": -1.5,
    "split": 0.5, "reverse-split": -1.0,

    # M&A
    "acquired": 1.0, "acquisition": 0.8, "acquirer": 0.5,
    "merger": 0.5, "merge": 0.5,
    "takeover": 0.5, "hostile": -1.0,
    "synergy": 0.8, "synergies": 0.8,
    "divest": -0.3, "divestiture": -0.3,

    # Operational
    "layoff": -1.5, "layoffs": -1.5, "firings": -1.5,
    "hiring": 1.0, "expansion": 1.5, "hiring-freeze": -1.0,
    "restructure": -1.0, "reorganization": -0.8,
    "outage": -1.5, "shutdown": -1.5,
    "recall": -2.0, "delay": -1.0, "delayed": -1.0,
    "discontinued": -1.2, "phased-out": -1.0,

    # Regulatory & legal
    "lawsuit": -1.5, "sued": -1.5, "settlement": -0.8,
    "investigation": -1.5, "probe": -1.2,
    "subpoena": -2.0, "indictment": -2.5, "indicted": -2.5,
    "fraud": -3.0, "scandal": -2.5, "manipulation": -2.5,
    "fine": -1.0, "fined": -1.0, "penalty": -1.0,
    "compliance": 0.3, "noncompliance": -1.5,
    "approval": 1.5, "approved": 1.5, "rejected": -1.5, "denied": -1.5,
    "fda-approval": 2.5, "fda-rejection": -2.5,
    "tariff": -1.5, "tariffs": -1.5, "sanctions": -1.5, "embargo": -2.0,

    # Valuation
    "overvalued": -1.0, "undervalued": 1.0,
    "premium": 0.5, "discount": 0.3,
    "expensive": -0.8, "cheap": 0.8,
    "stretched": -1.0, "compelling": 1.2,

    # Technical
    "overbought": -0.5, "oversold": 0.5,
    "breakout": 1.5, "breakdown": -1.5,
    "resistance": -0.3, "support": 0.3,
    "uptrend": 1.5, "downtrend": -1.5, "sideways": 0.0,
    "momentum": 0.5, "reversal": 0.0,
    "death-cross": -2.0, "golden-cross": 2.0,

    # Options-specific
    "calls": 0.3, "puts": -0.3,
    "skew": 0.0, "iv-spike": -1.0, "iv-crush": -0.5,
    "gamma-squeeze": 1.5, "short-squeeze": 1.8,
    "unusual-activity": 0.5,

    # Risk
    "risk-on": 1.5, "risk-off": -1.5,
    "flight-to-quality": -1.5, "safe-haven": -0.5,
    "contagion": -2.5, "systemic": -2.0,
    "tail-risk": -1.5, "blowup": -3.0,
    "drawdown": -1.0, "volatility": -0.3,

    # Sentiment / analyst tone
    "concerned": -1.0, "concerns": -1.0, "worry": -1.0, "worries": -1.0,
    "optimistic": 1.5, "pessimistic": -1.5,
    "bullishly": 2.0, "bearishly": -2.0,
    "encouraged": 1.2, "disappointed": -1.5, "disappointing": -1.8,
    "impressed": 1.5, "skeptical": -1.0, "cautious": -0.8,
    "constructive": 1.2, "destructive": -1.5,
}


# === Multi-word phrase lexicon (pre-matched before VADER) ===
_FINANCIAL_PHRASES: dict[str, float] = {
    "raised guidance": 2.5,
    "lowered guidance": -2.5,
    "withdrew guidance": -3.0,
    "missed estimates": -2.0, "beat estimates": 2.0,
    "missed expectations": -2.0, "beat expectations": 2.0,
    "fell short": -1.5,
    "going concern": -3.5,
    "material weakness": -2.5,
    "going public": 0.8,
    "going private": 0.5,
    "exploring strategic alternatives": -1.0,
    "executive departure": -1.5,
    "ceo resigned": -1.8, "ceo stepping down": -1.5, "ceo fired": -2.5,
    "ceo appointed": 1.0, "ceo named": 0.8,
    "share buyback": 1.5, "stock buyback": 1.5,
    "dividend cut": -2.5, "dividend suspended": -3.0,
    "dividend raised": 1.8, "dividend increased": 1.8,
    "credit rating cut": -2.0, "credit downgrade": -2.0,
    "credit upgrade": 2.0, "rating upgrade": 1.8,
    "earnings warning": -2.5, "profit warning": -2.5,
    "fda approval": 2.5, "fda approved": 2.5,
    "fda rejection": -2.5, "fda rejected": -2.5,
    "fda denied": -2.5, "complete response letter": -2.0,
    "going concern doubt": -3.5,
    "yield curve inverted": -2.0, "yield curve inversion": -2.0,
    "yield curve steepening": 0.8,
    "credit spreads widening": -2.0, "credit spreads tightening": 1.5,
    "vix spike": -1.5, "vix elevated": -1.0,
    "all time high": 1.5, "record high": 1.5, "fresh high": 1.2,
    "52 week high": 1.0, "52-week high": 1.0,
    "all time low": -1.5, "record low": -1.5,
    "52 week low": -1.0, "52-week low": -1.0,
    "short interest": -0.5, "short squeeze": 1.8,
    "insider buying": 1.5, "insider selling": -0.5,  # selling has many causes
    "cluster buying": 2.0,
    "stock soared": 2.5, "shares plunged": -2.5,
    "shares jumped": 1.8, "shares tumbled": -1.8,
    "stock surged": 2.0, "stock crashed": -3.0,
}


_analyzer: SentimentIntensityAnalyzer | None = None


def _get_analyzer() -> SentimentIntensityAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = SentimentIntensityAnalyzer()
        # VADER lexicon is keyed by lowercase tokens
        _analyzer.lexicon.update({k.lower(): v for k, v in _FINANCIAL_LEXICON.items()})
    return _analyzer


_PHRASE_RE = re.compile(
    r"|".join(re.escape(p) for p in sorted(_FINANCIAL_PHRASES.keys(), key=len, reverse=True)),
    re.IGNORECASE,
)


def _phrase_score(text: str) -> tuple[float, str]:
    """
    Pre-score multi-word phrases. Returns (sum_score, text_with_phrases_replaced).
    Phrases are replaced with empty space so VADER can tokenize the rest cleanly
    without double-counting their constituent words.
    """
    if not text:
        return 0.0, ""
    total = 0.0
    def _sub(m: re.Match) -> str:
        nonlocal total
        total += _FINANCIAL_PHRASES.get(m.group(0).lower(), 0.0)
        return " "
    cleaned = _PHRASE_RE.sub(_sub, text)
    return total, cleaned


def score_text(text: str) -> dict:
    """
    Score a single text string. Returns compound, pos, neg, neu, label.

    The compound is a blend of VADER's compound (after phrase removal) and
    the phrase score, normalized to roughly [-1, 1].
    """
    if not text or not text.strip():
        return {"compound": 0.0, "positive": 0.0, "negative": 0.0, "neutral": 1.0, "label": "neutral"}

    phrase_total, residual = _phrase_score(text)

    analyzer = _get_analyzer()
    vader_scores = analyzer.polarity_scores(residual or text)

    # Phrase score is in raw lexicon units; VADER's compound is normalized to [-1, 1].
    # Squish the phrase total through the same tanh-ish function VADER uses internally
    # (approximate: x / sqrt(x*x + 15)).
    if phrase_total != 0:
        phrase_compound = phrase_total / ((phrase_total * phrase_total + 15) ** 0.5)
    else:
        phrase_compound = 0.0

    # Weighted average: phrase signal counts heavier when present
    if phrase_total != 0:
        compound = 0.6 * phrase_compound + 0.4 * vader_scores["compound"]
    else:
        compound = vader_scores["compound"]

    compound = max(-1.0, min(1.0, compound))

    label = "positive" if compound >= 0.05 else "negative" if compound <= -0.05 else "neutral"
    return {
        "compound": round(compound, 4),
        "positive": round(vader_scores["pos"], 4),
        "negative": round(vader_scores["neg"], 4),
        "neutral": round(vader_scores["neu"], 4),
        "label": label,
    }


def score_articles(articles: list[dict]) -> dict:
    """
    Score a list of news articles. Each article should have 'title' and/or
    'description'. Returns per-article scores and aggregate metrics
    suitable for the Sentiment Agent and dashboard panels.
    """
    if not articles:
        return {"scores": [], "aggregate": {"compound": 0, "label": "neutral", "count": 0}}

    scores = []
    for article in articles:
        text = f"{article.get('title', '')} {article.get('description', '')}".strip()
        if not text:
            continue
        s = score_text(text)
        s["title"] = article.get("title", "")[:100]
        s["source"] = article.get("source", "")
        s["url"] = article.get("url", "")
        scores.append(s)

    if not scores:
        return {"scores": [], "aggregate": {"compound": 0, "label": "neutral", "count": 0}}

    compounds = [s["compound"] for s in scores]
    avg_compound = sum(compounds) / len(compounds)
    positive_count = sum(1 for c in compounds if c >= 0.05)
    negative_count = sum(1 for c in compounds if c <= -0.05)

    # Sentiment dispersion — high = mixed news flow, low = aligned
    if len(compounds) > 1:
        mean = avg_compound
        variance = sum((c - mean) ** 2 for c in compounds) / len(compounds)
        dispersion = round(variance ** 0.5, 4)
    else:
        dispersion = 0.0

    aggregate = {
        "compound": round(avg_compound, 4),
        "label": "positive" if avg_compound >= 0.05 else "negative" if avg_compound <= -0.05 else "neutral",
        "count": len(scores),
        "positive_count": positive_count,
        "negative_count": negative_count,
        "neutral_count": len(scores) - positive_count - negative_count,
        "bullish_pct": round(positive_count / len(scores) * 100, 1),
        "bearish_pct": round(negative_count / len(scores) * 100, 1),
        "dispersion": dispersion,
    }

    return {"scores": scores, "aggregate": aggregate}
