"""
News and sentiment data client.

Primary: NewsAPI.org (100 requests/day — treat every call as precious)
Supplementary: Finnhub (60 calls/min — more generous but still cached)

Used by the Sentiment Agent for news flow analysis and sentiment scoring.
"""

from newsapi import NewsApiClient
import httpx
import time
import logging

from config import settings

logger = logging.getLogger(__name__)

# Aggressive caching — news for a ticker doesn't change minute-to-minute
_NEWS_TTL = 1800       # 30 min — NewsAPI has 100/day, so cache hard
_FINNHUB_TTL = 900     # 15 min — Finnhub is more generous


class NewsDataClient:
    def __init__(self):
        self.newsapi = NewsApiClient(api_key=settings.NEWS_API_KEY)
        self.finnhub_key = settings.FINNHUB_API_KEY
        self._news_cache: dict[str, tuple[float, list]] = {}
        self._sentiment_cache: dict[str, tuple[float, dict]] = {}

    def get_ticker_news(
        self,
        ticker: str,
        page_size: int = 10,
    ) -> list[dict]:
        """
        Fetch recent news articles for a ticker.

        Default page_size is 10 (not 20) — we need enough for the
        Sentiment Agent to detect tone shifts, but not so many that
        we burn the 100/day limit analyzing 3 tickers.

        Returns articles with: title, description, source, publishedAt, url.
        We strip the full content to save memory — the agent uses titles
        and descriptions for sentiment scoring.
        """
        now = time.time()
        if ticker in self._news_cache:
            ts, data = self._news_cache[ticker]
            if (now - ts) < _NEWS_TTL:
                logger.debug(f"Returning cached news for {ticker}")
                return data

        response = self.newsapi.get_everything(
            q=ticker,
            sort_by="publishedAt",
            language="en",
            page_size=page_size,
        )

        articles = [
            {
                "title": a.get("title", ""),
                "description": a.get("description", ""),
                "source": a.get("source", {}).get("name", ""),
                "published_at": a.get("publishedAt", ""),
                "url": a.get("url", ""),
            }
            for a in response.get("articles", [])
        ]

        self._news_cache[ticker] = (now, articles)
        logger.info(f"Fetched {len(articles)} articles for {ticker}")
        return articles

    def get_market_sentiment_finnhub(self, ticker: str) -> dict:
        """
        Get company news from Finnhub (free-tier endpoint: /company-news).

        Returns recent headlines with sentiment metadata. The Sentiment Agent
        uses these alongside NewsAPI articles for cross-source validation.
        Finnhub often has different coverage than NewsAPI, so combining
        both gives a more complete picture.

        Returns: list of articles with headline, summary, source, datetime.
        """
        if not self.finnhub_key:
            logger.warning("FINNHUB_API_KEY not set, skipping Finnhub fetch")
            return {}

        now = time.time()
        if ticker in self._sentiment_cache:
            ts, data = self._sentiment_cache[ticker]
            if (now - ts) < _FINNHUB_TTL:
                logger.debug(f"Returning cached Finnhub news for {ticker}")
                return data

        from datetime import datetime, timedelta, timezone
        end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

        url = "https://finnhub.io/api/v1/company-news"
        params = {
            "symbol": ticker,
            "from": start,
            "to": end,
            "token": self.finnhub_key,
        }

        try:
            resp = httpx.get(url, params=params, timeout=10)
            resp.raise_for_status()
            articles = resp.json()
            # Only keep 15 most recent — conserve memory, agents don't need 200+
            trimmed = articles[:15]
            data = {
                "article_count": len(articles),
                "articles": [
                    {
                        "headline": a.get("headline", ""),
                        "summary": a.get("summary", "")[:200],
                        "source": a.get("source", ""),
                        "datetime": a.get("datetime", 0),
                        "url": a.get("url", ""),
                    }
                    for a in trimmed
                ],
            }
        except Exception as e:
            logger.warning(f"Finnhub company news fetch failed for {ticker}: {e}")
            return {}

        self._sentiment_cache[ticker] = (now, data)
        logger.info(f"Fetched {len(data['articles'])} Finnhub articles for {ticker}")
        return data

    def get_market_news_finnhub(
        self,
        category: str = "general",
    ) -> list[dict]:
        """
        Get general market news from Finnhub (not ticker-specific).

        Categories: general, forex, crypto, merger
        Used for broad market sentiment reads when the Macro Agent
        needs a news-level pulse alongside FRED data.
        """
        if not self.finnhub_key:
            return []

        url = "https://finnhub.io/api/v1/news"
        params = {"category": category, "token": self.finnhub_key}

        try:
            resp = httpx.get(url, params=params, timeout=10)
            resp.raise_for_status()
            articles = resp.json()
            # Only return the 10 most recent — agents don't need 50
            return articles[:10]
        except Exception as e:
            logger.warning(f"Finnhub market news fetch failed: {e}")
            return []
