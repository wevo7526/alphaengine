"""
Data-provided mode — the seam's request-scoped context.

A ContextVar holds the data supplied in the current request. When it is set
("provided mode"), the wrapped backend data-client methods (see install.py)
return data from this context and NEVER call the network; if the needed datum
isn't supplied, they raise FetchForbidden rather than silently fetching. This
is how authenticated/paying requests run with the fetch layer unreachable.

A defense-in-depth network guard additionally blocks DNS resolution to anything
non-local while a provided session is active, so even an un-wrapped code path
fails loudly instead of leaking a fetch. The wrapper short-circuit is the
primary guarantee; the network guard is the belt-and-suspenders proof.

Nothing here persists data: the ContextVar lives for the duration of the
`provided_session` and is reset on exit.
"""

from __future__ import annotations

import contextlib
import contextvars
import socket
from typing import Any, Optional

_provided: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "alphaengine_provided_data", default=None
)

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", ""}


class FetchForbidden(RuntimeError):
    """Raised when code attempts a network fetch while in data-provided mode."""


def is_provided_mode() -> bool:
    return _provided.get() is not None


def get_provided_data() -> Optional[dict]:
    return _provided.get()


def get_provided(domain: str, key: Optional[str] = None) -> Any:
    """Pull a datum from the provided-data context.

    `domain` is a bucket (e.g. "fundamentals", "price_history", "macro_snapshot").
    `key` selects within a keyed bucket (e.g. a ticker); omit it to return the
    whole bucket. Returns None when absent — the caller decides whether that is
    a FetchForbidden.
    """
    data = _provided.get()
    if data is None:
        return None
    bucket = data.get(domain)
    if key is None:
        return bucket
    if isinstance(bucket, dict):
        # Tolerate case-insensitive ticker keys.
        return bucket.get(key) if key in bucket else bucket.get(str(key).upper())
    return None


@contextlib.contextmanager
def _network_guard():
    """Block DNS to non-local hosts for the duration of the session."""
    orig = socket.getaddrinfo

    def blocked(host, *args, **kwargs):
        if str(host) in _LOCAL_HOSTS:
            return orig(host, *args, **kwargs)
        raise FetchForbidden(
            f"network egress to {host!r} blocked: data-provided mode is active "
            f"(supply this datum in the request payload instead of fetching)"
        )

    socket.getaddrinfo = blocked  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.getaddrinfo = orig  # type: ignore[assignment]


@contextlib.contextmanager
def provided_session(data: dict, *, guard_network: bool = True):
    """Enter data-provided mode for the duration of the block.

    `data`: the request's supplied data, bucketed by domain (see get_provided).
    `guard_network`: also install the DNS egress guard (default on). Set False
    only in unit tests that need to exercise the wrapper logic without touching
    the socket layer.
    """
    token = _provided.set(data or {})
    try:
        if guard_network:
            with _network_guard():
                yield
        else:
            yield
    finally:
        _provided.reset(token)
