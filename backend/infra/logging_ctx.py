"""
Request-scoped logging context.

A `request_id` is attached per incoming HTTP request via ASGI middleware,
then propagated into every log line using a ContextVar + logging.Filter.
Essential when two users run analyses simultaneously — without this,
their log lines interleave and debugging a failure becomes guesswork.

IMPORTANT: This is a pure ASGI middleware, NOT a Starlette
BaseHTTPMiddleware. BaseHTTPMiddleware buffers streaming response bodies
before sending them, which breaks our SSE `/api/analyze/stream` endpoint
and causes clients to hang on a perpetual loading state. ASGI middleware
passes chunks through unbuffered.

Usage:
  - install_logging() at startup
  - app.add_middleware(RequestIdMiddleware) on the FastAPI app
"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar

REQUEST_ID_HEADER = b"x-request-id"

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
    already = any(isinstance(f, RequestIdFilter) for f in root.filters)
    if not already:
        root.addFilter(RequestIdFilter())
    for h in root.handlers:
        already_h = any(isinstance(f, RequestIdFilter) for f in h.filters)
        if not already_h:
            h.addFilter(RequestIdFilter())
        fmt = h.formatter._fmt if h.formatter else None  # type: ignore[attr-defined]
        if fmt is None or "%(request_id)s" not in fmt:
            h.setFormatter(logging.Formatter(STRUCTURED_FORMAT))


class RequestIdMiddleware:
    """
    Pure ASGI middleware. Reads X-Request-ID from the incoming headers
    (or generates one), binds it to a ContextVar so log filters can see it,
    and echoes it on the response.

    Does NOT buffer response bodies — safe with StreamingResponse / SSE.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Pull or generate the request id from raw header bytes.
        rid: str | None = None
        for name, value in scope.get("headers", ()):  # list[tuple[bytes, bytes]]
            if name == REQUEST_ID_HEADER:
                try:
                    rid = value.decode("latin-1")
                except Exception:
                    rid = None
                break
        if not rid:
            rid = uuid.uuid4().hex[:12]

        token = _request_id_var.set(rid)
        rid_bytes = rid.encode("latin-1")

        async def send_with_header(message):
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers") or [])
                # Only append if upstream didn't already set one.
                if not any(h[0] == REQUEST_ID_HEADER for h in headers):
                    headers.append((REQUEST_ID_HEADER, rid_bytes))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            _request_id_var.reset(token)
