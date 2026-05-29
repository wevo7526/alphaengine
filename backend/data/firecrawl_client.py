"""
Firecrawl client — web scraping for cross-validating agent outputs.

Used by the Research Analyst to verify data against live web sources:
earnings reports, news articles, company filings, analyst reports.

Stability notes:
  - Firecrawl's Python SDK makes blocking HTTP calls with no native timeout
    control. We enforce a ceiling via `run_sync_with_timeout` in the async
    wrappers so one slow scrape can't stall an entire analysis.
  - Cache is bounded; without this, a long-lived singleton retains every
    URL ever scraped and grows without limit.
"""

from __future__ import annotations

import logging

from config import settings
from infra.async_utils import run_sync_with_timeout
from infra.cache import TTLCache

logger = logging.getLogger(__name__)

_CACHE_TTL = 1800  # 30 min
_SCRAPE_TIMEOUT = 20.0
_SEARCH_TIMEOUT = 20.0

_SCRAPE_CACHE: TTLCache[dict] = TTLCache(max_entries=256, ttl_seconds=_CACHE_TTL)
_SEARCH_CACHE: TTLCache[list[dict]] = TTLCache(max_entries=256, ttl_seconds=_CACHE_TTL)
# Full-document scrapes (filings, transcripts) are large; cache fewer, longer.
# Filings are immutable, so a 6h TTL is conservative — the evidence store
# provides the durable cross-restart cache.
_FULL_CACHE_TTL = 21600  # 6h
_FULL_TIMEOUT = 45.0
_FULL_CACHE: TTLCache[dict] = TTLCache(max_entries=64, ttl_seconds=_FULL_CACHE_TTL)


def _api_key() -> str:
    return getattr(settings, "FIRECRAWL_API_KEY", "") or ""


def scrape_url(url: str) -> dict:
    """Scrape a URL and return markdown content. Cached 30 min."""
    cached = _SCRAPE_CACHE.get(url)
    if cached is not None:
        return cached

    key = _api_key()
    if not key:
        return {"error": "FIRECRAWL_API_KEY not set", "content": "", "url": url}

    try:
        from firecrawl import FirecrawlApp
        app = FirecrawlApp(api_key=key)
        result = app.scrape(url, formats=["markdown"])

        title = ""
        if hasattr(result, "metadata") and isinstance(result.metadata, dict):
            title = result.metadata.get("title", "") or ""
        elif hasattr(result, "title"):
            title = getattr(result, "title", "") or ""

        data = {
            "url": url,
            "title": title,
            "content": (getattr(result, "markdown", "") or "")[:3000],
            "source": url,
        }
        _SCRAPE_CACHE.set(url, data)
        logger.info(f"Scraped {url}: {len(data['content'])} chars")
        return data
    except Exception as e:
        logger.warning(f"Firecrawl scrape failed for {url}: {e}")
        return {"error": str(e), "content": "", "url": url}


def search_web(query: str, limit: int = 3) -> list[dict]:
    """Search the web and return top results with content. Cached 30 min."""
    cache_key = f"search:{query}:{limit}"
    cached = _SEARCH_CACHE.get(cache_key)
    if cached is not None:
        return cached

    key = _api_key()
    if not key:
        return []

    try:
        from firecrawl import FirecrawlApp
        app = FirecrawlApp(api_key=key)
        results = app.search(query, limit=limit)

        items = []
        if hasattr(results, "web") and results.web:
            items.extend(results.web)
        if hasattr(results, "news") and results.news:
            items.extend(results.news)
        if not items and isinstance(results, list):
            items = results

        processed = []
        for r in items:
            title = getattr(r, "title", "") or ""
            url = getattr(r, "url", "") or ""
            content = getattr(r, "description", "") or getattr(r, "markdown", "") or ""
            if title or url:
                processed.append({"title": title, "url": url, "content": content[:1500]})

        _SEARCH_CACHE.set(cache_key, processed)
        logger.info(f"Web search '{query}': {len(processed)} results")
        return processed
    except Exception as e:
        logger.warning(f"Firecrawl search failed: {e}")
        return []


def scrape_full(url: str, max_chars: int = 120_000) -> dict:
    """Scrape a full document (filing / transcript) as markdown.

    Unlike `scrape_url` (3000-char cap for validation snippets), this keeps a
    large slice so downstream section parsing has the whole document to work
    with. Cached 6h. Used to pull public SEC filing HTML and IR/transcript
    pages via Firecrawl, offloading the heavy fetch from metered APIs.
    """
    cache_key = f"full:{url}:{max_chars}"
    cached = _FULL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    key = _api_key()
    if not key:
        return {"error": "FIRECRAWL_API_KEY not set", "content": "", "url": url}

    try:
        from firecrawl import FirecrawlApp
        app = FirecrawlApp(api_key=key)
        result = app.scrape(url, formats=["markdown"])
        title = ""
        if hasattr(result, "metadata") and isinstance(result.metadata, dict):
            title = result.metadata.get("title", "") or ""
        content = (getattr(result, "markdown", "") or "")[:max_chars]
        data = {"url": url, "title": title, "content": content, "source": url}
        _FULL_CACHE.set(cache_key, data)
        logger.info(f"Scraped full doc {url}: {len(content)} chars")
        return data
    except Exception as e:
        logger.warning(f"Firecrawl full scrape failed for {url}: {e}")
        return {"error": str(e), "content": "", "url": url}


# ── Async wrappers ────────────────────────────────────────────

async def ascrape_full(url: str, max_chars: int = 120_000) -> dict:
    try:
        return await run_sync_with_timeout(scrape_full, _FULL_TIMEOUT, url, max_chars)
    except TimeoutError:
        logger.warning(f"Firecrawl full scrape timed out: {url}")
        return {"error": "timeout", "content": "", "url": url}


async def ascrape_url(url: str) -> dict:
    try:
        return await run_sync_with_timeout(scrape_url, _SCRAPE_TIMEOUT, url)
    except TimeoutError:
        logger.warning(f"Firecrawl scrape timed out: {url}")
        return {"error": "timeout", "content": "", "url": url}


async def asearch_web(query: str, limit: int = 3) -> list[dict]:
    try:
        return await run_sync_with_timeout(search_web, _SEARCH_TIMEOUT, query, limit)
    except TimeoutError:
        logger.warning(f"Firecrawl search timed out: {query}")
        return []
