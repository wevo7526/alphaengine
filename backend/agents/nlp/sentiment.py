"""
Financial sentiment analysis pipeline.

Phase 1: VADER (rule-based, instant, no model download)
  - Tuned for financial text with custom lexicon additions
  - Good baseline for headline/description scoring

Phase 2 upgrade: FinBERT (ProsusAI/finbert, ~400MB)
  - Domain-specific financial sentiment
  - Better at nuanced financial language
  - Requires torch + transformers

Both expose the same interface so swapping is transparent.
"""

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import logging

logger = logging.getLogger(__name__)

# Financial lexicon additions — VADER doesn't know these are bearish/bullish
_FINANCIAL_LEXICON = {
    "bullish": 2.5,
    "bearish": -2.5,
    "upgrade": 2.0,
    "downgrade": -2.0,
    "outperform": 1.8,
    "underperform": -1.8,
    "beat": 1.5,
    "miss": -1.5,
    "beats": 1.5,
    "misses": -1.5,
    "rally": 2.0,
    "selloff": -2.0,
    "sell-off": -2.0,
    "surge": 2.0,
    "plunge": -2.5,
    "soar": 2.0,
    "tank": -2.0,
    "crash": -3.0,
    "recession": -2.5,
    "expansion": 1.5,
    "growth": 1.0,
    "decline": -1.5,
    "default": -3.0,
    "bankruptcy": -3.5,
    "dividend": 1.0,
    "buyback": 1.5,
    "restructuring": -1.0,
    "layoff": -1.5,
    "layoffs": -1.5,
    "guidance": 0.5,
    "raised guidance": 2.5,
    "lowered guidance": -2.5,
    "overvalued": -1.0,
    "undervalued": 1.0,
    "overbought": -0.5,
    "oversold": 0.5,
    "hawkish": -1.0,
    "dovish": 1.0,
    "tightening": -1.0,
    "easing": 1.0,
    "tariff": -1.5,
    "sanctions": -1.5,
}

_analyzer = None


def _get_analyzer() -> SentimentIntensityAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = SentimentIntensityAnalyzer()
        _analyzer.lexicon.update(_FINANCIAL_LEXICON)
    return _analyzer


def score_text(text: str) -> dict:
    """Score a single text string. Returns compound, pos, neg, neu scores."""
    analyzer = _get_analyzer()
    scores = analyzer.polarity_scores(text)
    return {
        "compound": round(scores["compound"], 4),
        "positive": round(scores["pos"], 4),
        "negative": round(scores["neg"], 4),
        "neutral": round(scores["neu"], 4),
        "label": "positive" if scores["compound"] >= 0.05 else "negative" if scores["compound"] <= -0.05 else "neutral",
    }


def score_articles(articles: list[dict]) -> dict:
    """
    Score a list of news articles. Each article should have 'title' and/or 'description'.
    Returns per-article scores + aggregate metrics.
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
        scores.append(s)

    if not scores:
        return {"scores": [], "aggregate": {"compound": 0, "label": "neutral", "count": 0}}

    compounds = [s["compound"] for s in scores]
    avg_compound = sum(compounds) / len(compounds)
    positive_count = sum(1 for c in compounds if c >= 0.05)
    negative_count = sum(1 for c in compounds if c <= -0.05)

    aggregate = {
        "compound": round(avg_compound, 4),
        "label": "positive" if avg_compound >= 0.05 else "negative" if avg_compound <= -0.05 else "neutral",
        "count": len(scores),
        "positive_count": positive_count,
        "negative_count": negative_count,
        "neutral_count": len(scores) - positive_count - negative_count,
        "bullish_pct": round(positive_count / len(scores) * 100, 1),
        "bearish_pct": round(negative_count / len(scores) * 100, 1),
    }

    return {"scores": scores, "aggregate": aggregate}
