"""Request body size limits, enforced before the body is parsed (T7 spec §4.4).

A FastAPI dependency can't do this: Starlette has already spooled the whole multipart
body by the time dependencies run. This pure ASGI middleware checks `Content-Length`
up front and also counts the bytes actually received, so a chunked or lying client
is cut off too. Requests that match no rule are untouched.
"""

from __future__ import annotations

import re

import structlog
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = structlog.get_logger()

MB = 1024 * 1024


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, rules: list[tuple[str, str, int]]) -> None:
        """`rules`: (method, path regex, max body bytes); the first match wins."""
        self.app = app
        self.rules = [(m.upper(), re.compile(p), n) for m, p, n in rules]

    def _limit_for(self, scope: Scope) -> int | None:
        for method, pattern, max_bytes in self.rules:
            if scope["method"] == method and pattern.match(scope["path"]):
                return max_bytes
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self._limit_for(scope)
        if limit is None:
            await self.app(scope, receive, send)
            return

        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await self._reject(scope, receive, send, limit)
            return

        received = 0
        exceeded = False
        started = False

        async def limited_receive() -> Message:
            nonlocal received, exceeded
            if exceeded:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    raise _BodyTooLarge
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if exceeded:
                # The app turned the aborted read into its own error (FastAPI makes it a
                # 400 "error parsing the body"); drop that and send the 413 below.
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _BodyTooLarge:
            pass
        if exceeded and not started:
            await self._reject(scope, receive, send, limit)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send, limit: int) -> None:
        logger.warning("request_too_large", path=scope["path"], limit=limit)
        response = JSONResponse(
            status_code=413,
            content={
                "error": "REQUEST_TOO_LARGE",
                "message": f"Request body must be at most {limit / MB:g} MB",
            },
        )
        await response(scope, receive, send)
