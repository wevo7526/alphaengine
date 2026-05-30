"""
Provided-data mode for the backend desk (the seam, backend-side).

Lets the FULL 5-agent desk (orchestrator.run_research_desk) run without pulling
any commercial data: in provided-mode every data-client egress method returns
data supplied in the request, or raises FetchForbidden — it never fetches. The
agents then reason over the caller's data using the quant math as tools.

Outside provided-mode (the Demo Desk / eval path) the wrappers are transparent:
they call the original method and fetch sample data as before. So this is purely
additive — install once at startup, engage per slate request via provided_session.

The LLM (Anthropic) and DB egress are NOT blocked (the agents need to reason and
the orchestrator reads continuity). The no-fetch guarantee is enforced at the
data-client method boundary, which is where commercial market data enters.
"""

from __future__ import annotations

import contextlib
import contextvars
import functools
import importlib
import inspect
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_provided: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "ae_backend_provided_data", default=None
)


class FetchForbidden(RuntimeError):
    """Raised when the desk attempts to fetch data not supplied in provided-mode."""


def is_provided_mode() -> bool:
    return _provided.get() is not None


def get_provided(domain: str, key: Optional[str] = None) -> Any:
    data = _provided.get()
    if data is None:
        return None
    bucket = data.get(domain)
    if key is None:
        return bucket
    if isinstance(bucket, dict):
        return bucket.get(key) if key in bucket else bucket.get(str(key).upper())
    return None


@contextlib.contextmanager
def provided_session(data: dict):
    token = _provided.set(data or {})
    try:
        yield
    finally:
        _provided.reset(token)


def _first_upper(args, kwargs):
    if args:
        return str(args[0]).upper()
    for k in ("ticker", "symbol", "series_id", "cik"):
        if k in kwargs:
            return str(kwargs[k]).upper()
    return None


def _none_key(args, kwargs):
    return None


# (module_path, attr_holder, name, domain, key_fn). attr_holder "class" means a
# class method on `name`'s class; "module" means a module-level function.
_CLASS_SPECS = [
    ("data.market_client", "MarketDataClient", "get_fundamentals", "fundamentals", _first_upper),
    ("data.market_client", "MarketDataClient", "get_price_history", "price_history", _first_upper),
    ("data.market_client", "MarketDataClient", "get_total_return_history", "total_return_history", _first_upper),
    ("data.market_client", "MarketDataClient", "get_options_chain", "options_chain", _first_upper),
    ("data.market_client", "MarketDataClient", "get_earnings_calendar", "earnings_calendar", _first_upper),
    ("data.market_client", "MarketDataClient", "get_consensus", "consensus", _first_upper),
    ("data.fred_client", "FREDDataClient", "get_macro_snapshot", "macro_snapshot", _none_key),
    ("data.fred_client", "FREDDataClient", "get_series_history", "series_history", _first_upper),
    ("data.fred_client", "FREDDataClient", "get_single_indicator", "series_history", _first_upper),
    ("data.fred_client", "FREDDataClient", "get_risk_free_rate", "risk_free_rate", _none_key),
    ("data.news_client", "NewsDataClient", "get_ticker_news", "ticker_news", _first_upper),
    ("data.news_client", "NewsDataClient", "get_market_sentiment_finnhub", "news_sentiment", _first_upper),
    ("data.news_client", "NewsDataClient", "get_market_news_finnhub", "market_news", _none_key),
    ("data.sec_client", "SECDataClient", "get_recent_filings", "recent_filings", _first_upper),
    ("data.sec_client", "SECDataClient", "get_filings_by_date_range", "filings_by_date", _first_upper),
    ("data.sec_client", "SECDataClient", "search_filings_fulltext", "filings_fulltext", _none_key),
    ("data.sec_client", "SECDataClient", "extract_mda", "filing_section", _none_key),
    ("data.sec_client", "SECDataClient", "extract_risk_factors", "filing_section", _none_key),
    ("data.sec_client", "SECDataClient", "extract_financial_statements", "filing_section", _none_key),
    ("data.sec_client", "SECDataClient", "extract_business_description", "filing_section", _none_key),
    ("data.sec_client", "SECDataClient", "get_insider_trades", "insider_trades", _first_upper),
    ("data.sec_client", "SECDataClient", "get_13f_holdings", "holdings_13f", _first_upper),
    ("data.sec_client", "SECDataClient", "search_13f_for_ticker", "holdings_13f", _first_upper),
    ("data.alpha_vantage_client", "AlphaVantageClient", "get_top_movers", "movers", _none_key),
    ("data.alpha_vantage_client", "AlphaVantageClient", "get_rsi", "indicators", _first_upper),
    ("data.alpha_vantage_client", "AlphaVantageClient", "get_macd", "indicators", _first_upper),
    ("data.alpha_vantage_client", "AlphaVantageClient", "get_bollinger_bands", "indicators", _first_upper),
    ("data.alpha_vantage_client", "AlphaVantageClient", "get_sma", "indicators", _first_upper),
    ("data.alpha_vantage_client", "AlphaVantageClient", "get_ema", "indicators", _first_upper),
]

# Module-level functions (firecrawl + screener). domain they'll never be given
# -> always FetchForbidden in provided-mode (block-only; no provided data path).
_MODULE_SPECS = [
    ("data.firecrawl_client", "scrape_url", "web"),
    ("data.firecrawl_client", "search_web", "web"),
    ("data.firecrawl_client", "scrape_full", "web"),
    ("data.firecrawl_client", "ascrape_url", "web"),
    ("data.firecrawl_client", "asearch_web", "web"),
    ("data.firecrawl_client", "ascrape_full", "web"),
    ("data.market_screener", "screen_market", "screen"),
    ("data.market_screener", "screen_market_tickers", "screen"),
]

_installed = False
_originals: list = []


def _make_wrapper(orig: Callable, label: str, domain: str, key_fn: Callable):
    is_async = inspect.iscoroutinefunction(orig)
    if is_async:
        @functools.wraps(orig)
        async def awrapper(*args, **kwargs):
            if is_provided_mode():
                # strip self for bound-style call: first arg is self for methods
                lookup_args = args[1:] if args else args
                val = get_provided(domain, key_fn(lookup_args, kwargs))
                if val is not None:
                    return val
                raise FetchForbidden(f"{label}: not in provided data (fetch disabled)")
            return await orig(*args, **kwargs)
        return awrapper

    @functools.wraps(orig)
    def wrapper(*args, **kwargs):
        if is_provided_mode():
            lookup_args = args[1:] if args else args
            val = get_provided(domain, key_fn(lookup_args, kwargs))
            if val is not None:
                return val
            raise FetchForbidden(f"{label}: not in provided data (fetch disabled)")
        return orig(*args, **kwargs)
    return wrapper


def install_provided_mode() -> None:
    """Idempotently wrap backend data-client egress so provided-mode never fetches.
    Transparent (calls originals) when not in provided-mode."""
    global _installed
    if _installed:
        return
    wrapped = 0
    for module_path, class_name, method, domain, key_fn in _CLASS_SPECS:
        try:
            cls = getattr(importlib.import_module(module_path), class_name)
        except Exception as e:  # noqa: BLE001
            logger.debug("provided_data: skip %s.%s (%s)", module_path, class_name, e)
            continue
        for m in (method, "a" + method):
            orig = getattr(cls, m, None)
            if orig is None or getattr(orig, "__ae_provided__", False):
                continue
            w = _make_wrapper(orig, f"{class_name}.{m}", domain, key_fn)
            w.__ae_provided__ = True
            setattr(cls, m, w)
            _originals.append((cls, m, orig))
            wrapped += 1
    for module_path, fn_name, domain in _MODULE_SPECS:
        try:
            mod = importlib.import_module(module_path)
        except Exception:  # noqa: BLE001
            continue
        orig = getattr(mod, fn_name, None)
        if orig is None or getattr(orig, "__ae_provided__", False):
            continue
        w = _make_wrapper(orig, f"{module_path}.{fn_name}", domain, _none_key)
        w.__ae_provided__ = True
        setattr(mod, fn_name, w)
        _originals.append((mod, fn_name, orig))
        wrapped += 1
    _installed = True
    logger.info("provided_data: wrapped %d data-egress points", wrapped)


def uninstall_provided_mode() -> None:
    global _installed
    for holder, name, orig in reversed(_originals):
        setattr(holder, name, orig)
    _originals.clear()
    _installed = False
