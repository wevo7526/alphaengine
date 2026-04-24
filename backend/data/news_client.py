"""
News and sentiment data client.

Primary: NewsAPI.org (100 requests/day — treat every call as precious)
Supplementary: Finnhub (60 calls/min — more generous but still cached)

Used by the Sentiment Agent for news flow analysis and sentiment scoring.

Stability notes:
  - All Finnhub HTTP calls go through infra.http (retries + honours Retry-After).
  - NewsAPI's client is synchronous; wrap in run_sync when called from async.
  - Bounded caches prevent heap growth under sustained traffic.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from newsapi import NewsApiClient

from config import settings
from infra.async_utils import run_sync
from infra.cache import TTLCache
from infra.http import HttpError, http_get_json

logger = logging.getLogger(__name__)

_NEWS_TTL = 1800       # 30 min — NewsAPI has 100/day, cache hard
_FINNHUB_TTL = 900     # 15 min — Finnhub is more generous


class NewsDataClient:
    def __init__(self):
        self.newsapi = NewsApiClient(api_key=settings.NEWS_API_KEY) if settings.NEWS_API_KEY else None
        self.finnhub_key = settings.FINNHUB_API_KEY
        self._news_cache: TTLCache[list[dict]] = TTLCache(max_entries=256, ttl_seconds=_NEWS_TTL)
        self._sentiment_cache: TTLCache[dict] = TTLCache(max_entries=256, ttl_seconds=_FINNHUB_TTL)

    def get_ticker_news(self, ticker: str, page_size: int = 10) -> list[dict]:
        """Fetch recent news articles for a ticker via NewsAPI."""
        if self.newsapi is None:
            logger.debug("NewsAPI not configured — skipping ticker news")
            return []

        cached = self._news_cache.get(ticker)
        if cached is not None:
            logger.debug(f"Returning cached news for {ticker}")
            return cached

        try:
            response = self.newsapi.get_everything(
                q=ticker,
                sort_by="publishedAt",
                language="en",
                page_size=page_size,
            )
        except Exception as e:
            logger.warning(f"NewsAPI fetch failed for {ticker}: {e}")
            return []

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
        self._news_cache.set(ticker, articles)
        logger.info(f"Fetched {len(articles)} articles for {ticker}")
        return articles

    def get_market_sentiment_finnhub(self, ticker: str) -> dict:
        """Get company news from Finnhub (free-tier endpoint)."""
        if not self.finnhub_key:
            logger.debug("FINNHUB_API_KEY not set, skipping Finnhub fetch")
            return {}

        cached = self._sentiment_cache.get(ticker)
        if cached is not None:
            logger.debug(f"Returning cached Finnhub news for {ticker}")
            return cached

        end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

        try:
            articles = http_get_json(
                "https://finnhub.io/api/v1/company-news",
                params={"symbol": ticker, "from": start, "to": end, "token": self.finnhub_key},
                read_timeout=10,
                total_timeout=15,
                max_retries=2,
                label=f"finnhub.company-news({ticker})",
            )
        except HttpError as e:
            logger.warning(f"Finnhub company news failed for {ticker}: {e}")
            return {}

        if not isinstance(articles, list):
            logger.warning(f"Finnhub returned unexpected shape for {ticker}: {type(articles).__name__}")
            return {}

        trimmed = articles[:15]
        data = {
            "article_count": len(articles),
            "articles": [
                {
                    "headline": a.get("headline", ""),
                    "summary": (a.get("summary") or "")[:200],
                    "source": a.get("source", ""),
                    "datetime": a.get("datetime", 0),
                    "url": a.get("url", ""),
                }
                for a in trimmed
            ],
        }
        self._sentiment_cache.set(ticker, data)
        logger.info(f"Fetched {len(data['articles'])} Finnhub articles for {ticker}")
        return data

    def get_market_news_finnhub(self, category: str = "general") -> list[dict]:
        if not self.finnhub_key:
            return []
        try:
            articles = http_get_json(
                "https://finnhub.io/api/v1/news",
                params={"category": category, "token": self.finnhub_key},
                read_timeout=10,
                total_timeout=15,
                max_retries=2,
                label=f"finnhub.news({category})",
            )
        except HttpError as e:
            logger.warning(f"Finnhub market news failed: {e}")
            return []
        if not isinstance(articles, list):
            return []
        return articles[:10]

    # ── Async wrappers ────────────────────────────────────────────

    async def aget_ticker_news(self, ticker: str, page_size: int = 10) -> list[dict]:
        return await run_sync(self.get_ticker_news, ticker, page_size)

    async def aget_market_sentiment_finnhub(self, ticker: str) -> dict:
        return await run_sync(self.get_market_sentiment_finnhub, ticker)

    async def aget_market_news_finnhub(self, category: str = "general") -> list[dict]:
        return await run_sync(self.get_market_news_finnhub, category)
