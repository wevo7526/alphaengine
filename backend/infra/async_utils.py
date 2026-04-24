"""
Async helpers — keep the event loop unblocked.

The platform has many synchronous library calls (yfinance, fredapi, sec-api,
newsapi-python). Running them directly inside async route handlers or agent
coroutines starves the event loop. One slow yfinance call → every concurrent
request hangs behind it.

`run_sync` dispatches blocking work onto a thread pool, returning control
to the loop until the work finishes. `ablock_sleep` is the async-safe
replacement for `time.sleep` inside async retry loops.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any, Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def run_sync(fn: Callable[..., T], /, *args, **kwargs) -> T:
    """
    Dispatch a blocking callable onto the default loop executor.

    Use this for any sync library call that touches the network, disk,
    or performs meaningful CPU work. Do NOT use it for trivial pure-Python
    work — the thread-hop overhead costs more than you save.
    """
    loop = asyncio.get_running_loop()
    if kwargs:
        fn = functools.partial(fn, **kwargs)
    return await loop.run_in_executor(None, fn, *args)


async def run_sync_with_timeout(
    fn: Callable[..., T],
    timeout: float,
    *args,
    **kwargs,
) -> T:
    """`run_sync` with an enforced deadline. Cancels the wait on timeout."""
    return await asyncio.wait_for(run_sync(fn, *args, **kwargs), timeout=timeout)


async def gather_bounded(
    coros: list[Awaitable[T]],
    *,
    limit: int = 8,
    return_exceptions: bool = True,
) -> list[T | BaseException]:
    """
    asyncio.gather but with a concurrency cap. Prevents fan-out blowups
    (e.g., "fetch news for 30 tickers in parallel" hammering rate limits).
    """
    sem = asyncio.Semaphore(limit)

    async def _run(c: Awaitable[T]) -> T:
        async with sem:
            return await c

    return await asyncio.gather(*(_run(c) for c in coros), return_exceptions=return_exceptions)
