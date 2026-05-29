"""
FRED (Federal Reserve Economic Data) client.

Provides macro-economic indicators that the Macro Regime Analyst uses
to classify the current environment as expansion, late-cycle, contraction,
or recovery.

Rate limit: 120 requests/minute (generous, but we still cache).

Stability notes:
  - fredapi is synchronous and makes HTTPS calls. Sync methods are safe from
    worker threads; async wrappers dispatch to run_sync so the event loop
    stays free.
  - Caches are bounded to prevent unbounded heap growth.
  - Retry uses async sleep when called from async paths. The sync fallback
    stays simple because it only runs from thread-pool workers.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from datetime import datetime, timedelta, timezone

from fredapi import Fred

from config import settings
from infra.async_utils import run_sync
from infra.cache import TTLCache

logger = logging.getLogger(__name__)


# Per-call HTTP timeout applied to fredapi's underlying requests session.
# fredapi defers entirely to `requests` and never sets a socket timeout, so
# without this a slow/hung FRED endpoint stalls forever. We patch it once
# at process import time so the cap covers every call site.
_FRED_HTTP_TIMEOUT_SECONDS = 6.0


def _install_fredapi_http_timeout() -> None:
    """Wrap fredapi's internal request method to enforce a hard HTTP timeout.

    fredapi 0.5.x uses `urllib.request.urlopen` (no `requests.Session`), so
    we monkey-patch `Fred._Fred__fetch_data` indirectly by overriding the
    `urlopen` call path. Simplest robust shim: subclass the urlopen-style
    call by replacing `Fred.get_series` to call the original via a thread
    with a hard cap is overkill. Instead, patch `urllib.request.urlopen`
    in the fredapi module to inject a default timeout.
    """
    try:
        import fredapi.fred as _fmod  # type: ignore[attr-defined]
    except Exception:
        return
    if getattr(_fmod, "_alphaengine_timeout_installed", False):
        return
    original_urlopen = getattr(_fmod, "urlopen", None)
    if original_urlopen is None:
        return

    def _patched(url, *args, **kwargs):
        kwargs.setdefault("timeout", _FRED_HTTP_TIMEOUT_SECONDS)
        return original_urlopen(url, *args, **kwargs)

    _fmod.urlopen = _patched  # type: ignore[assignment]
    _fmod._alphaengine_timeout_installed = True  # type: ignore[attr-defined]
    logger.info(f"FRED HTTP timeout installed ({_FRED_HTTP_TIMEOUT_SECONDS}s)")


_install_fredapi_http_timeout()


class _FREDCircuitBreaker:
    """Short-circuit FRED calls when the upstream is clearly broken.

    Tracks consecutive failures. Once `failure_threshold` is reached, every
    subsequent call returns immediately (treated as failure) for
    `cooldown_seconds`. A single success during cooldown resets the breaker.

    Why this matters: without it, every dashboard hit spawns 13 retrying
    series fetches × 3 attempts × jittered backoff. With FRED down, a
    request that should return in milliseconds (cached) sits for minutes,
    monopolises the thread pool, and starves every other endpoint.
    """

    def __init__(self, failure_threshold: int = 5, cooldown_seconds: float = 60.0):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._open_until: float = 0.0

    def allow(self) -> bool:
        with self._lock:
            return time.time() >= self._open_until

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._open_until = 0.0

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.failure_threshold:
                self._open_until = time.time() + self.cooldown_seconds
                logger.warning(
                    f"FRED circuit breaker OPEN for {self.cooldown_seconds:.0f}s "
                    f"after {self._consecutive_failures} consecutive failures"
                )


_breaker = _FREDCircuitBreaker(failure_threshold=5, cooldown_seconds=60.0)


def _retry_fetch(fn, retries: int = 1, base_delay: float = 0.4):
    """Retry a FRED API call with jittered backoff.

    Retries are deliberately short (1 retry, ~0.4s base) because we're
    typically inside a 6-12s wall-clock budget. The breaker handles the
    "FRED is down" case so we don't keep hammering.
    """
    if not _breaker.allow():
        return None
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            result = fn()
            if result is not None:
                _breaker.record_success()
                return result
        except Exception as e:
            last_exc = e
            logger.debug(f"FRED retry {attempt + 1}/{retries}: {e}")
        if attempt < retries:
            wait = base_delay * (2 ** attempt) + random.uniform(0, 0.2)
            time.sleep(wait)
    _breaker.record_failure()
    if last_exc is not None:
        raise last_exc
    return None


# Series IDs mapped to human-readable names.
MACRO_SERIES = {
    "DFF": "fed_funds_rate",           # Monetary policy stance
    "T10Y2Y": "yield_curve_spread",    # Inversion = recession signal
    "T10YIE": "breakeven_inflation",   # Market inflation expectations
    "BAMLH0A0HYM2": "credit_spreads",  # Risk appetite (wide = fear)
    "VIXCLS": "vix",                   # Implied volatility / fear gauge
    "UNRATE": "unemployment",          # Labor market health (monthly)
    "CPIAUCSL": "cpi",                 # Inflation level (monthly)
    "GDP": "real_gdp",                 # Growth trajectory (quarterly)
    "WALCL": "fed_balance_sheet",      # Liquidity conditions (weekly)
    "DCOILWTICO": "wti_crude",         # Energy / inflation input
    "DTWEXBGS": "usd_index",           # Dollar strength
    "M2SL": "m2_money_supply",         # Monetary aggregate (monthly)
    "ICSA": "jobless_claims",          # High-frequency labor signal (weekly)
}


class FREDDataClient:
    # TTLs are intentionally long. FRED data is daily-cadence (most series
    # publish at end-of-day or weekly), so refreshing hourly was wasteful
    # AND was the main reason a single FRED stutter could break the
    # dashboard — every dashboard load that arrived after the hourly cache
    # expired triggered a fresh fetch. 6 hours means at most 4 cold fetches
    # per day per worker. Combined with startup pre-warm, the user almost
    # never hits a cold path.
    _SNAPSHOT_TTL = 6 * 3600
    _SERIES_TTL = 6 * 3600
    _SINGLE_TTL = 3 * 3600

    # Concurrency cap. Was 6, but combined with the series fetcher's own
    # workers, that was ~10 concurrent FRED calls per macro request, and
    # fredapi returns None under burst load (silent throttling). 3 keeps us
    # well within FRED's comfort zone and only adds a couple seconds.
    _SNAPSHOT_WORKERS = 3

    def __init__(self):
        self.fred = Fred(api_key=settings.FRED_API_KEY)
        # One-slot "cache" for the full snapshot so concurrent requests share.
        self._snapshot_cache: dict | None = None
        self._snapshot_timestamp: float = 0
        self._series_cache: TTLCache[list[dict]] = TTLCache(
            max_entries=256, ttl_seconds=self._SERIES_TTL,
        )
        # Stale-while-error fallback for series. Same shape as the
        # in-band cache but never expires; only updated on successful
        # fetches. Read on failure so the dashboard always has *something*.
        self._series_last_good: dict[str, list[dict]] = {}
        self._single_cache: TTLCache[dict] = TTLCache(
            max_entries=128, ttl_seconds=self._SINGLE_TTL,
        )

    # Per-call hard timeout when refreshing. Tightened because the previous
    # 8/12s budget was being silently violated: `with ThreadPoolExecutor`
    # blocks on `__exit__` until every worker returns, so a single slow
    # fredapi call (no HTTP timeout pre-fix) could hold the request for
    # minutes. We now manage the pool manually and cancel pending futures
    # at the deadline, so the wall budget is actually enforced.
    _PER_FETCH_TIMEOUT = 6.0
    _SNAPSHOT_WALL_TIMEOUT = 8.0

    def get_macro_snapshot(self) -> dict:
        """Pull latest values for all key macro indicators.

        Stale-while-error: if we have ANY previously-built snapshot in
        memory, we return it on refresh failure rather than letting the
        dashboard sit on a timeout. The cache TTL is treated as soft — a
        background-style refresh only replaces the cached value when the
        new fetch actually succeeds.
        """
        now = time.time()
        if self._snapshot_cache and (now - self._snapshot_timestamp) < self._SNAPSHOT_TTL:
            logger.debug("Returning cached macro snapshot")
            return self._snapshot_cache

        # Circuit breaker open → don't even try. Serve stale if we have it.
        if not _breaker.allow():
            if self._snapshot_cache:
                logger.warning("FRED breaker open; serving stale snapshot")
                return self._snapshot_cache
            logger.warning("FRED breaker open and no cache; returning empty snapshot")
            return {}

        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _fetch_one(series_id: str, name: str) -> tuple[str, dict | None]:
            try:
                series = _retry_fetch(lambda sid=series_id: self.fred.get_series(sid))
                if series is None:
                    return name, None
                series = series.dropna()
                if len(series) < 2:
                    return name, None
                return name, {
                    "value": float(series.iloc[-1]),
                    "previous": float(series.iloc[-2]),
                    "change": float(series.iloc[-1] - series.iloc[-2]),
                    "date": str(series.index[-1].date()),
                    "series_id": series_id,
                }
            except Exception as e:
                logger.warning(f"Failed to fetch {series_id} ({name}): {e}")
                return name, None

        snapshot: dict = {}
        deadline = time.time() + self._SNAPSHOT_WALL_TIMEOUT

        # Manual pool management — DO NOT use `with` block, because its
        # `__exit__` calls shutdown(wait=True) and would block until every
        # worker drained, defeating the wall timeout.
        pool = ThreadPoolExecutor(
            max_workers=self._SNAPSHOT_WORKERS,
            thread_name_prefix="fred-snap",
        )
        try:
            futures = {
                pool.submit(_fetch_one, sid, name): name
                for sid, name in MACRO_SERIES.items()
            }
            try:
                for future in as_completed(futures, timeout=self._SNAPSHOT_WALL_TIMEOUT):
                    remaining = max(0.25, deadline - time.time())
                    try:
                        name, data = future.result(timeout=min(self._PER_FETCH_TIMEOUT, remaining))
                    except Exception as e:
                        logger.warning(f"FRED worker timeout/failure: {e}")
                        continue
                    if data:
                        snapshot[name] = data
                    if time.time() >= deadline:
                        logger.warning(
                            f"FRED snapshot wall deadline hit ({self._SNAPSHOT_WALL_TIMEOUT}s); "
                            f"returning {len(snapshot)} indicators"
                        )
                        break
            except Exception as e:
                # `as_completed` raised TimeoutError — drop through with
                # whatever we have so far.
                logger.warning(f"FRED snapshot deadline: {e}")
        finally:
            # Non-blocking shutdown. cancel_futures stops queued tasks; the
            # in-flight ones are abandoned. They'll die quickly because the
            # underlying HTTP call also has a hard timeout.
            try:
                pool.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                # Python <3.9 fallback (shouldn't happen in our deploy env).
                pool.shutdown(wait=False)

        # Stale-while-error: refresh failed entirely AND we have a prior
        # snapshot. Keep serving the prior one — better than a blank dashboard.
        if not snapshot and self._snapshot_cache:
            logger.warning(
                "FRED snapshot empty; returning stale cache from %.0fs ago",
                now - self._snapshot_timestamp,
            )
            return self._snapshot_cache

        if snapshot:
            self._snapshot_cache = snapshot
            self._snapshot_timestamp = now
        logger.info(f"Macro snapshot built: {len(snapshot)}/{len(MACRO_SERIES)} indicators")
        return snapshot

    def get_series_history(self, series_id: str, lookback_days: int = 252) -> list[dict]:
        cache_key = f"{series_id}:{lookback_days}"
        cached = self._series_cache.get(cache_key)
        if cached is not None:
            logger.debug(f"Returning cached series {series_id}")
            return cached

        start = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        try:
            series = _retry_fetch(
                lambda: self.fred.get_series(series_id, observation_start=start)
            )
        except Exception as e:
            logger.warning(f"FRED series {series_id} failed: {e}")
            # Stale-while-error: serve the last-good observation set if we
            # ever managed a successful fetch. Better an hour-old curve than
            # an empty chart.
            stale = self._series_last_good.get(cache_key)
            if stale:
                logger.warning(f"Serving stale series {series_id} ({len(stale)} obs)")
                return stale
            return []
        if series is None:
            stale = self._series_last_good.get(cache_key)
            if stale:
                logger.warning(f"FRED returned None for {series_id}; serving stale cache ({len(stale)} obs)")
                return stale
            return []
        series = series.dropna()
        result = [
            {"date": str(idx.date()), "value": float(val)}
            for idx, val in series.items()
        ]
        self._series_cache.set(cache_key, result)
        # Mirror to the never-expiring last-good cache for stale-while-error.
        self._series_last_good[cache_key] = result
        logger.info(f"Fetched {len(result)} observations for {series_id}")
        return result

    def get_risk_free_rate(self) -> float:
        """
        Fetch current 3-month Treasury yield (DGS3MO) as the risk-free rate.

        Falls back to 4% if FRED is unreachable. Result is decimal (0.045 for
        4.5%) and cached via the underlying single-indicator cache (1h TTL),
        so this is cheap to call repeatedly.

        Why DGS3MO and not Fed funds: Treasuries are the textbook risk-free
        proxy for Sharpe-style calculations, and DGS3MO closely tracks the
        Fed funds path while being a true tradable rate.
        """
        try:
            data = self.get_single_indicator("DGS3MO")
            if data and data.get("value") is not None:
                # FRED returns DGS3MO as a percentage (e.g. 5.25 for 5.25%)
                pct = float(data["value"])
                if 0 < pct < 25:  # sanity bounds
                    return pct / 100.0
        except Exception as e:
            logger.warning(f"get_risk_free_rate fallback to 4% (FRED failed: {e})")
        return 0.04

    def get_single_indicator(self, series_id: str) -> dict | None:
        cached = self._single_cache.get(series_id)
        if cached is not None:
            return cached
        try:
            series = _retry_fetch(lambda: self.fred.get_series(series_id))
            if series is None:
                return None
            series = series.dropna()
            if len(series) < 2:
                return None
            data = {
                "value": float(series.iloc[-1]),
                "previous": float(series.iloc[-2]),
                "change": float(series.iloc[-1] - series.iloc[-2]),
                "date": str(series.index[-1].date()),
                "series_id": series_id,
            }
            self._single_cache.set(series_id, data)
            return data
        except Exception as e:
            logger.warning(f"Failed to fetch {series_id}: {e}")
            return None

    # ── Async wrappers ────────────────────────────────────────────
    # Snapshot internally uses a ThreadPoolExecutor, so calling it from
    # within `run_sync` (itself in a thread) is still safe — threads can
    # spawn threads.

    async def aget_macro_snapshot(self) -> dict:
        return await run_sync(self.get_macro_snapshot)

    async def aget_series_history(self, series_id: str, lookback_days: int = 252) -> list[dict]:
        return await run_sync(self.get_series_history, series_id, lookback_days)

    async def aget_single_indicator(self, series_id: str) -> dict | None:
        return await run_sync(self.get_single_indicator, series_id)
