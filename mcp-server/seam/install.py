"""
Install the data-provided seam over the intact backend.

`install_seam()` monkeypatches the backend data-client egress methods so that,
in provided mode, they return data from the request context and never fetch.
Out of provided mode (unauthenticated demo / eval), they call the original and
fetch as before. The backend source is untouched on disk; the gateway installs
this at boot. There is no backend -> gateway import.

Each wrapper, in provided mode:
  - returns the supplied datum if present, else
  - raises FetchForbidden — it NEVER calls the original fetch.
So a paid/authenticated request (always provided mode) cannot reach the network
through these methods. A test asserts the original is never invoked.

Coverage is the set of egress methods the agent desk + quant actually call
(see docs/INVENTORY.md). Add a row to _SPECS to wrap another method.
"""

from __future__ import annotations

import functools
import logging
from typing import Callable

from seam.data_context import FetchForbidden, get_provided, is_provided_mode

logger = logging.getLogger(__name__)

_installed = False
_originals: list[tuple[type, str, Callable]] = []


def _first_upper(args, kwargs):
    if args:
        return str(args[0]).upper()
    # method(ticker=...) style
    for k in ("ticker", "symbol", "series_id"):
        if k in kwargs:
            return str(kwargs[k]).upper()
    return None


def _none_key(args, kwargs):
    return None


# (module_path, class_name, method, domain, key_fn)
_SPECS = [
    ("data.market_client", "MarketDataClient", "get_fundamentals", "fundamentals", _first_upper),
    ("data.market_client", "MarketDataClient", "get_price_history", "price_history", _first_upper),
    ("data.market_client", "MarketDataClient", "get_total_return_history", "total_return_history", _first_upper),
    ("data.market_client", "MarketDataClient", "get_options_chain", "options_chain", _first_upper),
    ("data.fred_client", "FREDDataClient", "get_macro_snapshot", "macro_snapshot", _none_key),
    ("data.fred_client", "FREDDataClient", "get_series_history", "series_history", _first_upper),
    ("data.fred_client", "FREDDataClient", "get_risk_free_rate", "risk_free_rate", _none_key),
    ("data.news_client", "NewsDataClient", "get_ticker_news", "ticker_news", _first_upper),
    ("data.sec_client", "SECDataClient", "get_recent_filings", "recent_filings", _first_upper),
    ("data.sec_client", "SECDataClient", "get_insider_trades", "insider_trades", _first_upper),
]


def _wrap(cls: type, method: str, domain: str, key_fn: Callable) -> None:
    orig = getattr(cls, method)
    if getattr(orig, "__ae_seam__", False):
        return  # already wrapped

    @functools.wraps(orig)
    def wrapper(self, *args, **kwargs):
        if is_provided_mode():
            key = key_fn(args, kwargs)
            val = get_provided(domain, key)
            if val is not None:
                return val
            raise FetchForbidden(
                f"{cls.__name__}.{method}({key!r}) is not present in the provided "
                f"data and fetching is disabled in data-provided mode — supply "
                f"'{domain}'{'' if key is None else f'[{key!r}]'} in the request payload"
            )
        return orig(self, *args, **kwargs)

    wrapper.__ae_seam__ = True  # type: ignore[attr-defined]
    setattr(cls, method, wrapper)
    _originals.append((cls, method, orig))


def install_seam() -> None:
    """Idempotently wrap the backend data-client egress methods."""
    global _installed
    if _installed:
        return
    import importlib

    wrapped = 0
    for module_path, class_name, method, domain, key_fn in _SPECS:
        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
        except Exception as e:  # noqa: BLE001 — a missing client shouldn't abort boot
            logger.warning("seam: could not load %s.%s (%s)", module_path, class_name, e)
            continue
        if not hasattr(cls, method):
            logger.warning("seam: %s has no method %s", class_name, method)
            continue
        _wrap(cls, method, domain, key_fn)
        wrapped += 1
    _installed = True
    logger.info("seam: installed over %d backend data-client methods", wrapped)


def uninstall_seam() -> None:
    """Restore the original methods (test isolation)."""
    global _installed
    for cls, method, orig in reversed(_originals):
        setattr(cls, method, orig)
    _originals.clear()
    _installed = False
