"""
Firecrawl client — web scraping for cross-validating agent outputs.

Used by the Research Analyst to verify data against live web sources:
earnings reports, news articles, company filings, analyst reports.
"""

import logging
import time

from config import settings

logger = logging.getLogger(__name__)

_CACHE: dict[str, tuple[float, dict]] = {}
_CACHE_TTL = 1800  # 30 min cache


def scrape_url(url: str) -> dict:
    """Scrape a URL and return markdown content. Cached 30 min."""
    now = time.time()
    if url in _CACHE:
        ts, data = _CACHE[url]
        if (now - ts) < _CACHE_TTL:
            return data

    api_key = settings.FIRECRAWL_API_KEY if hasattr(settings, "FIRECRAWL_API_KEY") else ""
    if not api_key:
        return {"error": "FIRECRAWL_API_KEY not set", "content": ""}

    try:
        from firecrawl import FirecrawlApp
        app = FirecrawlApp(api_key=api_key)
        result = app.scrape(url, formats=["markdown"])

        data = {
            "url": url,
            "title": getattr(result, "title", "") or result.metadata.get("title", "") if hasattr(result, "metadata") else "",
            "content": (getattr(result, "markdown", "") or "")[:3000],
            "source": url,
        }
        _CACHE[url] = (now, data)
        logger.info(f"Scraped {url}: {len(data['content'])} chars")
        return data
    except Exception as e:
        logger.warning(f"Firecrawl scrape failed for {url}: {e}")
        return {"error": str(e), "content": "", "url": url}


def search_web(query: str, limit: int = 3) -> list[dict]:
    """Search the web and return top results with content. Cached 30 min."""
    cache_key = f"search:{query}"
    now = time.time()
    if cache_key in _CACHE:
        ts, data = _CACHE[cache_key]
        if (now - ts) < _CACHE_TTL:
            return data.get("results", [])

    api_key = settings.FIRECRAWL_API_KEY if hasattr(settings, "FIRECRAWL_API_KEY") else ""
    if not api_key:
        return []

    try:
        from firecrawl import FirecrawlApp
        app = FirecrawlApp(api_key=api_key)
        results = app.search(query, limit=limit)

        # Firecrawl v2 returns SearchData with .web and .news lists
        items = []
        if hasattr(results, "web") and results.web:
            items.extend(results.web)
        if hasattr(results, "news") and results.news:
            items.extend(results.news)
        # Fallback for older SDK versions that return a list
        if not items and isinstance(results, list):
            items = results

        processed = []
        for r in items:
            title = getattr(r, "title", "") or ""
            url = getattr(r, "url", "") or ""
            content = getattr(r, "description", "") or getattr(r, "markdown", "") or ""

            if title or url:
                processed.append({
                    "title": title,
                    "url": url,
                    "content": content[:1500],
                })

        _CACHE[cache_key] = (now, {"results": processed})
        logger.info(f"Web search '{query}': {len(processed)} results")
        return processed
    except Exception as e:
        logger.warning(f"Firecrawl search failed: {e}")
        return []
