"""
Request-scoped logging context.

A `request_id` is attached per incoming HTTP request via middleware,
then propagated into every log line using a ContextVar + logging.Filter.
Essential when two users run analyses simultaneously — without this,
their log lines interleave and debugging a failure becomes guesswork.

Usage:
  - logging.basicConfig(format=STRUCTURED_FORMAT) at startup
  - app.add_middleware(RequestIdMiddleware) on the FastAPI app
  - Inside code: no changes needed — the filter injects %(request_id)s
"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

REQUEST_ID_HEADER = "X-Request-ID"

_request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

STRUCTURED_FORMAT = "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get()
        return True


def get_request_id() -> str:
    return _request_id_var.get()


def set_request_id(value: str) -> None:
    _request_id_var.set(value)


def install_logging() -> None:
    """Call once at app startup. Idempotent."""
    root = logging.getLogger()
    # Avoid duplicate filters on reload.
    already = any(isinstance(f, RequestIdFilter) for f in root.filters)
    if not already:
        root.addFilter(RequestIdFilter())
    for h in root.handlers:
        already_h = any(isinstance(f, RequestIdFilter) for f in h.filters)
        if not already_h:
            h.addFilter(RequestIdFilter())
        # Upgrade format if the existing formatter lacks request_id
        fmt = h.formatter._fmt if h.formatter else None  # type: ignore[attr-defined]
        if fmt is None or "%(request_id)s" not in fmt:
            h.setFormatter(logging.Formatter(STRUCTURED_FORMAT))


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:12]
        token = _request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            _request_id_var.reset(token)
        response.headers[REQUEST_ID_HEADER] = rid
        return response
