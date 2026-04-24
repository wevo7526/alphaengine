"""
Resilient HTTP primitives.

Every outbound HTTP call from the data layer should go through
`http_get_json` / `http_get` (sync) or `ahttp_get_json` (async).
They provide:

  - Connect + read timeouts (no unbounded hangs)
  - Exponential backoff retries on 5xx + connection errors
  - Honouring Retry-After on 429 rate limits
  - Jitter so concurrent retries don't thundering-herd
  - Clear, structured logging for every failure

Rate-limited 4xx responses other than 429 are NOT retried — they are the
server's considered answer, not a transient fault. Retrying a 400 just
burns quota.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any, Callable

import httpx

logger = logging.getLogger(__name__)

DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 20.0
DEFAULT_TOTAL_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_BACKOFF = 0.5  # seconds; grows 0.5, 1.0, 2.0, 4.0 ...
MAX_BACKOFF = 30.0

_RETRIABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


def _jitter(base: float) -> float:
    """Full jitter: 0..base. Protects against retry storms."""
    return random.uniform(0, base)


def _backoff_seconds(attempt: int, base: float = DEFAULT_BASE_BACKOFF) -> float:
    return min(MAX_BACKOFF, base * (2 ** attempt)) + _jitter(base)


def _retry_after_seconds(resp: httpx.Response | None) -> float | None:
    if resp is None:
        return None
    value = resp.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None  # HTTP-date form is rare and not worth parsing


def _build_timeout(
    connect: float | None,
    read: float | None,
    total: float | None,
) -> httpx.Timeout:
    return httpx.Timeout(
        connect=connect if connect is not None else DEFAULT_CONNECT_TIMEOUT,
        read=read if read is not None else DEFAULT_READ_TIMEOUT,
        write=DEFAULT_READ_TIMEOUT,
        pool=total if total is not None else DEFAULT_TOTAL_TIMEOUT,
    )


class HttpError(Exception):
    """Normalised HTTP failure after retries are exhausted."""

    def __init__(self, message: str, status: int | None = None, url: str | None = None):
        super().__init__(message)
        self.status = status
        self.url = url


def http_get(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    connect_timeout: float | None = None,
    read_timeout: float | None = None,
    total_timeout: float | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_backoff: float = DEFAULT_BASE_BACKOFF,
    label: str = "http",
) -> httpx.Response:
    """Resilient synchronous GET. Raises HttpError if retries are exhausted."""
    timeout = _build_timeout(connect_timeout, read_timeout, total_timeout)
    last_error: Exception | None = None
    last_status: int | None = None

    for attempt in range(max_retries + 1):
        try:
            resp = httpx.get(url, params=params, headers=headers, timeout=timeout)
            last_status = resp.status_code
            if resp.status_code < 400:
                return resp
            if resp.status_code not in _RETRIABLE_STATUS:
                # Client error — retrying won't change the answer.
                raise HttpError(
                    f"{label} HTTP {resp.status_code}: {resp.text[:200]}",
                    status=resp.status_code,
                    url=url,
                )
            # Retriable. Prefer server-specified backoff.
            ra = _retry_after_seconds(resp)
            wait = ra if ra is not None else _backoff_seconds(attempt, base_backoff)
            logger.warning(
                "[%s] %s retriable status=%s attempt=%s/%s wait=%.2fs",
                label, url, resp.status_code, attempt + 1, max_retries + 1, wait,
            )
            last_error = HttpError(
                f"{label} retriable status {resp.status_code}",
                status=resp.status_code, url=url,
            )
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout, httpx.RemoteProtocolError) as e:
            wait = _backoff_seconds(attempt, base_backoff)
            logger.warning(
                "[%s] %s transport error=%s attempt=%s/%s wait=%.2fs",
                label, url, type(e).__name__, attempt + 1, max_retries + 1, wait,
            )
            last_error = e
        except HttpError:
            raise
        except Exception as e:  # noqa: BLE001 — last-resort
            logger.error("[%s] %s unexpected error: %s", label, url, e)
            raise HttpError(f"{label} unexpected error: {e}", url=url) from e

        if attempt < max_retries:
            time.sleep(wait)

    raise HttpError(
        f"{label} exhausted {max_retries + 1} attempts (last status={last_status})",
        status=last_status,
        url=url,
    ) from last_error


def http_get_json(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    connect_timeout: float | None = None,
    read_timeout: float | None = None,
    total_timeout: float | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    label: str = "http",
) -> Any:
    """Resilient GET that returns decoded JSON. Raises HttpError on failure."""
    resp = http_get(
        url,
        params=params,
        headers=headers,
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        total_timeout=total_timeout,
        max_retries=max_retries,
        label=label,
    )
    try:
        return resp.json()
    except ValueError as e:
        raise HttpError(f"{label} invalid JSON: {e}", status=resp.status_code, url=url) from e


async def ahttp_get(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    connect_timeout: float | None = None,
    read_timeout: float | None = None,
    total_timeout: float | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_backoff: float = DEFAULT_BASE_BACKOFF,
    label: str = "http",
    client: httpx.AsyncClient | None = None,
) -> httpx.Response:
    """Resilient asynchronous GET."""
    timeout = _build_timeout(connect_timeout, read_timeout, total_timeout)
    last_error: Exception | None = None
    last_status: int | None = None

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=timeout)

    try:
        for attempt in range(max_retries + 1):
            try:
                resp = await client.get(url, params=params, headers=headers, timeout=timeout)
                last_status = resp.status_code
                if resp.status_code < 400:
                    return resp
                if resp.status_code not in _RETRIABLE_STATUS:
                    raise HttpError(
                        f"{label} HTTP {resp.status_code}: {resp.text[:200]}",
                        status=resp.status_code,
                        url=url,
                    )
                ra = _retry_after_seconds(resp)
                wait = ra if ra is not None else _backoff_seconds(attempt, base_backoff)
                logger.warning(
                    "[%s] %s retriable status=%s attempt=%s/%s wait=%.2fs",
                    label, url, resp.status_code, attempt + 1, max_retries + 1, wait,
                )
                last_error = HttpError(
                    f"{label} retriable status {resp.status_code}",
                    status=resp.status_code, url=url,
                )
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout, httpx.RemoteProtocolError) as e:
                wait = _backoff_seconds(attempt, base_backoff)
                logger.warning(
                    "[%s] %s transport error=%s attempt=%s/%s wait=%.2fs",
                    label, url, type(e).__name__, attempt + 1, max_retries + 1, wait,
                )
                last_error = e
            except HttpError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.error("[%s] %s unexpected error: %s", label, url, e)
                raise HttpError(f"{label} unexpected error: {e}", url=url) from e

            if attempt < max_retries:
                await asyncio.sleep(wait)

        raise HttpError(
            f"{label} exhausted {max_retries + 1} attempts (last status={last_status})",
            status=last_status,
            url=url,
        ) from last_error
    finally:
        if own_client:
            await client.aclose()


async def ahttp_get_json(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    connect_timeout: float | None = None,
    read_timeout: float | None = None,
    total_timeout: float | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    label: str = "http",
) -> Any:
    resp = await ahttp_get(
        url,
        params=params,
        headers=headers,
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        total_timeout=total_timeout,
        max_retries=max_retries,
        label=label,
    )
    try:
        return resp.json()
    except ValueError as e:
        raise HttpError(f"{label} invalid JSON: {e}", status=resp.status_code, url=url) from e


def run_with_timeout(fn: Callable[..., Any], timeout: float, *args, **kwargs) -> Any:
    """
    Not-safe wrapper for when you must run a sync call with an enforceable deadline.
    Uses a thread so that pure-CPU hangs can still be timed out.
    """
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FTimeout

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(fn, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except FTimeout as e:
            future.cancel()
            raise TimeoutError(f"{getattr(fn, '__name__', 'fn')} exceeded {timeout}s") from e
