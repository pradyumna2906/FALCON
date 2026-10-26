"""FastAPI exception handlers for the shared safe error contract."""

import logging
import re
import traceback
from collections.abc import Mapping
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from falcon_api.core.errors import ApplicationError
from falcon_api.core.request_context import (
    REQUEST_ID_HEADER,
    get_request_id,
    resolve_request_id,
)
from falcon_api.schemas.errors import ErrorDetail, ErrorResponse, ValidationIssue

logger = logging.getLogger("falcon_api.errors")

_PUBLIC_HTTP_HEADERS = frozenset({"allow", "retry-after", "www-authenticate"})
_VALIDATION_MESSAGES = {
    "missing": "Field is required.",
    "extra_forbidden": "Unexpected field.",
    "string_too_short": "Value is too short.",
    "string_too_long": "Value is too long.",
    "int_parsing": "Value has an invalid format.",
    "float_parsing": "Value has an invalid format.",
    "bool_parsing": "Value has an invalid format.",
    "date_from_datetime_parsing": "Value has an invalid format.",
    "datetime_from_date_parsing": "Value has an invalid format.",
    "enum": "Value is not permitted.",
    "literal_error": "Value is not permitted.",
    "greater_than": "Value is outside the allowed range.",
    "greater_than_equal": "Value is outside the allowed range.",
    "less_than": "Value is outside the allowed range.",
    "less_than_equal": "Value is outside the allowed range.",
}


def register_exception_handlers(application: FastAPI) -> None:
    """Register the complete exception-to-response mapping once per app."""
    application.add_exception_handler(
        RequestValidationError,
        validation_exception_handler,
    )
    application.add_exception_handler(
        ApplicationError,
        application_exception_handler,
    )
    application.add_exception_handler(
        StarletteHTTPException,
        http_exception_handler,
    )
    application.add_exception_handler(Exception, unexpected_exception_handler)


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Return bounded field feedback without reflecting rejected values."""
    details = tuple(
        _validation_issue(error)
        for error in exc.errors()[:20]
    )
    return _error_response(
        request=request,
        status_code=422,
        code="validation_error",
        message="Request validation failed.",
        details=details,
    )


async def application_exception_handler(
    request: Request,
    exc: ApplicationError,
) -> JSONResponse:
    """Expose only the explicit public contract of an expected error."""
    return _error_response(
        request=request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.public_message,
    )


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    """Normalize framework HTTP failures without reflecting custom detail."""
    code, message = _http_error_contract(exc.status_code)
    return _error_response(
        request=request,
        status_code=exc.status_code,
        code=code,
        message=message,
        headers=_public_http_headers(exc.headers),
    )


async def unexpected_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Log a sanitized stack and return a generic internal error."""
    request_id = _request_id_for(request)
    logger.error(
        "unexpected_error",
        extra={
            "request_id": request_id,
            "error_type": type(exc).__name__,
            "stack": _safe_stack(exc),
        },
    )
    return _error_response(
        request=request,
        status_code=500,
        code="internal_server_error",
        message="An unexpected error occurred.",
        request_id=request_id,
    )


def _error_response(
    *,
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: tuple[ValidationIssue, ...] | None = None,
    headers: dict[str, str] | None = None,
    request_id: str | None = None,
) -> JSONResponse:
    resolved_request_id = request_id or _request_id_for(request)
    response = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            request_id=resolved_request_id,
            timestamp=datetime.now(UTC),
            details=details,
        ),
    )
    response_headers = dict(headers or {})
    response_headers[REQUEST_ID_HEADER] = resolved_request_id
    return JSONResponse(
        status_code=status_code,
        content=response.model_dump(mode="json", exclude_none=True),
        headers=response_headers,
    )


def _public_http_headers(
    headers: Mapping[str, str] | None,
) -> dict[str, str]:
    if headers is None:
        return {}
    return {
        name: value
        for name, value in headers.items()
        if name.lower() in _PUBLIC_HTTP_HEADERS
    }


def _request_id_for(request: Request) -> str:
    candidate = getattr(request.state, "request_id", None) or get_request_id()
    return resolve_request_id(candidate)


def _validation_issue(error: dict[str, Any]) -> ValidationIssue:
    location = error.get("loc", ("request",))
    safe_parts = [
        re.sub(r"[^A-Za-z0-9_-]", "_", str(part))[:64]
        for part in location
    ]
    field = ".".join(part for part in safe_parts if part)[:256] or "request"
    error_type = str(error.get("type", ""))
    return ValidationIssue(
        field=field,
        message=_VALIDATION_MESSAGES.get(error_type, "Invalid value."),
    )


def _http_error_contract(status_code: int) -> tuple[str, str]:
    try:
        status = HTTPStatus(status_code)
    except ValueError:
        return "http_error", "The HTTP request failed."
    return status.name.lower(), f"{status.phrase}."


def _safe_stack(exc: Exception) -> list[dict[str, str | int]]:
    return [
        {
            "file": Path(frame.filename).name,
            "function": frame.name,
            "line": frame.lineno,
        }
        for frame in traceback.extract_tb(exc.__traceback__)
    ]
