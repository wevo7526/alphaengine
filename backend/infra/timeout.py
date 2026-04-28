"""
Global request-timeout middleware.

A pure ASGI middleware (not BaseHTTPMiddleware — the latter buffers streaming
bodies and would defeat SSE) that wraps every request in `asyncio.wait_for`
and returns 504 Gateway Timeout if the handler runs longer than the configured
deadline.

The point: no backend handler can ever cause a frontend "perpetual loading"
state. Either it returns within the budget, or the client gets a 504 and
the loading-state UI transitions to error.

Streaming endpoints (SSE) are exempt — they're long-lived by design. Match
them by path prefix.
"""

from __future__ import annotations

import asyncio
import json
import logging

logger = logging.getLogger(__name__)


class RequestTimeoutMiddleware:
    def __init__(
        self,
        app,
        *,
        timeout_seconds: float = 90.0,
        exempt_path_prefixes: tuple[str, ...] = ("/api/analyze/stream",),
    ):
        self.app = app
        self.timeout = timeout_seconds
        self.exempt = exempt_path_prefixes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if any(path.startswith(p) for p in self.exempt):
            await self.app(scope, receive, send)
            return

        # We have to track whether the response has started, because once
        # headers are sent we can't return a 504 — we just have to abort.
        response_started = False

        async def send_wrapper(message):
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await asyncio.wait_for(
                self.app(scope, receive, send_wrapper),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            logger.error(
                "Request exceeded %.1fs deadline: %s %s",
                self.timeout,
                scope.get("method"),
                path,
            )
            if response_started:
                # Headers already on the wire — best we can do is stop sending.
                return
            body = json.dumps({
                "detail": f"Request exceeded {int(self.timeout)}s deadline",
                "code": "request_timeout",
            }).encode("utf-8")
            await send({
                "type": "http.response.start",
                "status": 504,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            })
            await send({"type": "http.response.body", "body": body})
