"""ASGI request correlation and body-free access logging."""

import logging
from time import perf_counter

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from falcon_api.core.request_context import (
    REQUEST_ID_HEADER,
    bind_request_id,
    resolve_request_id,
)

logger = logging.getLogger("falcon_api.http")


class RequestContextMiddleware:
    """Attach a safe request ID and structured metadata to every HTTP request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = resolve_request_id(
            Headers(scope=scope).get(REQUEST_ID_HEADER),
        )
        scope.setdefault("state", {})["request_id"] = request_id

        method = scope.get("method", "UNKNOWN")
        path = scope.get("path", "")[:2048]
        status_code = 500
        error_type: str | None = None
        started_at = perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                response_headers = MutableHeaders(scope=message)
                response_headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            with bind_request_id(request_id):
                await self.app(scope, receive, send_with_request_id)
        except Exception as exc:
            error_type = type(exc).__name__
            raise
        finally:
            duration_ms = round((perf_counter() - started_at) * 1000, 3)
            event = "request_failed" if error_type else "request_completed"
            level = logging.ERROR if error_type else logging.INFO
            logger.log(
                level,
                event,
                extra={
                    "request_id": request_id,
                    "http_method": method,
                    "http_path": path,
                    "http_status": status_code,
                    "duration_ms": duration_ms,
                    "error_type": error_type,
                },
            )
