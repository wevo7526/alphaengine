"""
News and sentiment data client.

Source: Massive ticker-news feed (api.massive.com — Polygon.io-compatible),
with Firecrawl web search as a fallback when the Massive feed is empty.

Used by the Sentiment / Research agents for news flow analysis and sentiment
scoring.

Data-layer consolidation note:
  - NewsAPI.org and Finnhub have been REMOVED. All news now flows through
    `data.massive_client.ticker_news` (primary) and `data.firecrawl_client`
    (fallback). The `_finnhub` suffix on two public methods is LEGACY — the
    names are retained ONLY because callers (agents/research_analyst.py)
    depend on them. They no longer touch Finnhub.

Stability notes:
  - All HTTP work happens inside massive_client / firecrawl_client, which
    already go through infra.http (retries + Retry-After) and enforce
    timeouts. Nothing here raises — failures degrade to the empty shape.
  - Bounded caches prevent heap growth under sustained traffic.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from data import firecrawl_client
from data import massive_client
from infra.async_utils import run_sync
from infra.cache import TTLCache

logger = logging.getLogger(__name__)

_NEWS_TTL = 1800       # 30 min — news cadence; matches the old NewsAPI budget
_SENTIMENT_TTL = 900   # 15 min — company-news rollup cache


def _to_epoch_seconds(published_at: str | None) -> int:
    """Best-effort convert an ISO-8601 publish timestamp to epoch seconds.

    The legacy Finnhub shape exposed a `datetime` int (epoch seconds); some
    callers may key off it, so we preserve an int there. Returns 0 when the
    value is missing or unparseable.
    """
    if not published_at:
        return 0
    try:
        s = published_at.strip()
        # Normalise a trailing 'Z' to an explicit UTC offset for fromisoformat.
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return 0


class NewsDataClient:
    def __init__(self):
        self._news_cache: TTLCache[list[dict]] = TTLCache(max_entries=256, ttl_seconds=_NEWS_TTL)
        self._sentiment_cache: TTLCache[dict] = TTLCache(max_entries=256, ttl_seconds=_SENTIMENT_TTL)

    def get_ticker_news(self, ticker: str, page_size: int = 10) -> list[dict]:
        """Fetch recent news articles for a ticker via the Massive news feed.

        Returns a list of {title, description, source, published_at, url} dicts
        — the same shape the old NewsAPI client produced, so the Sentiment
        Agent needs zero changes.
        """
        if not ticker:
            return []

        cache_key = f"{ticker.upper()}:{page_size}"
        cached = self._news_cache.get(cache_key)
        if cached is not None:
            logger.debug("Returning cached news for %s", ticker)
            return cached

        # massive_client.ticker_news already returns the canonical
        # {title, description, source, published_at, url} shape.
        articles = massive_client.ticker_news(ticker, limit=page_size)
        articles = [
            {
                "title": a.get("title") or "",
                "description": a.get("description") or "",
                "source": a.get("source") or "",
                "published_at": a.get("published_at") or "",
                "url": a.get("url") or "",
            }
            for a in (articles or [])
        ]

        # Fallback: if Massive has no coverage for this ticker, try a Firecrawl
        # web search so the agent still sees *some* recent flow.
        if not articles:
            try:
                results = firecrawl_client.search_web(f"{ticker} stock news", limit=page_size)
            except Exception as e:  # noqa: BLE001 — a news source must never crash a run
                logger.warning("Firecrawl news fallback failed for %s: %s", ticker, e)
                results = []
            articles = [
                {
                    "title": r.get("title") or "",
                    "description": (r.get("content") or "")[:500],
                    "source": r.get("url") or "",
                    "published_at": "",
                    "url": r.get("url") or "",
                }
                for r in (results or [])
            ]

        self._news_cache.set(cache_key, articles)
        logger.info("Fetched %d articles for %s", len(articles), ticker)
        return articles

    def get_market_sentiment_finnhub(self, ticker: str) -> dict:
        """Company-news rollup for a ticker.

        LEGACY NAME — no longer touches Finnhub. Sourced from the Massive news
        feed and reshaped into the historical Finnhub return contract:
            {article_count, articles: [{headline, summary, source, datetime, url}]}
        so agents/research_analyst.py needs zero changes.
        """
        if not ticker:
            return {}

        tk = ticker.upper()
        cached = self._sentiment_cache.get(tk)
        if cached is not None:
            logger.debug("Returning cached company news for %s", ticker)
            return cached

        # Reuse the ticker-news path (cached) so we don't double-fetch.
        articles = self.get_ticker_news(ticker, page_size=15)
        if not articles:
            return {}

        trimmed = articles[:15]
        data = {
            "article_count": len(articles),
            "articles": [
                {
                    "headline": a.get("title") or "",
                    "summary": (a.get("description") or "")[:200],
                    "source": a.get("source") or "",
                    "datetime": _to_epoch_seconds(a.get("published_at")),
                    "url": a.get("url") or "",
                }
                for a in trimmed
            ],
        }
        self._sentiment_cache.set(tk, data)
        logger.info("Fetched %d company-news articles for %s", len(data["articles"]), ticker)
        return data

    def get_market_news_finnhub(self, category: str = "general") -> list[dict]:
        """General (non-ticker) market news headlines.

        LEGACY NAME — no longer touches Finnhub. Massive has no broad
        market-news endpoint, so this is sourced from a Firecrawl web search.
        Preserves the historical list return shape; returns [] on failure or
        when Firecrawl is not configured.
        """
        query = f"{category} stock market news today" if category else "stock market news today"
        try:
            results = firecrawl_client.search_web(query, limit=10)
        except Exception as e:  # noqa: BLE001 — a news source must never crash a run
            logger.warning("Firecrawl market news failed (%s): %s", category, e)
            return []
        return [
            {
                "headline": r.get("title") or "",
                "summary": (r.get("content") or "")[:200],
                "source": r.get("url") or "",
                "url": r.get("url") or "",
            }
            for r in (results or [])
        ]

    # ── Async wrappers ────────────────────────────────────────────

    async def aget_ticker_news(self, ticker: str, page_size: int = 10) -> list[dict]:
        return await run_sync(self.get_ticker_news, ticker, page_size)

    async def aget_market_sentiment_finnhub(self, ticker: str) -> dict:
        return await run_sync(self.get_market_sentiment_finnhub, ticker)

    async def aget_market_news_finnhub(self, category: str = "general") -> list[dict]:
        return await run_sync(self.get_market_news_finnhub, category)
