"""Request-correlation context independent of the HTTP framework."""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4

REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")

_request_id: ContextVar[str | None] = ContextVar(
    "falcon_request_id",
    default=None,
)


def resolve_request_id(candidate: str | None) -> str:
    """Retain a safe client identifier or generate a private replacement."""
    if candidate is not None and REQUEST_ID_PATTERN.fullmatch(candidate) is not None:
        return candidate
    return uuid4().hex


@contextmanager
def bind_request_id(request_id: str) -> Iterator[None]:
    """Bind a request ID for the duration of one request task."""
    token = _request_id.set(request_id)
    try:
        yield
    finally:
        _request_id.reset(token)


def get_request_id() -> str | None:
    """Return the request ID bound to the current asynchronous context."""
    return _request_id.get()
