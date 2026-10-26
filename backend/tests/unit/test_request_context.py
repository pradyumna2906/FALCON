"""Request correlation and body-free access-log tests."""

import logging
import re

import pytest
from falcon_api.core.config import Settings
from falcon_api.core.logging import JsonLogFormatter, configure_logging
from falcon_api.core.request_context import (
    REQUEST_ID_PATTERN,
    bind_request_id,
    get_request_id,
    resolve_request_id,
)
from falcon_api.main import create_app
from fastapi import Response
from fastapi.testclient import TestClient


def test_missing_request_id_is_generated(client: TestClient) -> None:
    response = client.get("/health/live")

    assert REQUEST_ID_PATTERN.fullmatch(response.headers["X-Request-ID"])


def test_safe_incoming_request_id_is_retained(client: TestClient) -> None:
    request_id = "client.Request_123:attempt-4"

    response = client.get(
        "/health/live",
        headers={"X-Request-ID": request_id},
    )

    assert response.headers["X-Request-ID"] == request_id


@pytest.mark.parametrize(
    "unsafe_request_id",
    [
        " leading-space",
        "contains/slash",
        "contains=equals",
        "x" * 65,
    ],
)
def test_unsafe_request_id_is_replaced(
    client: TestClient,
    unsafe_request_id: str,
) -> None:
    response = client.get(
        "/health/live",
        headers={"X-Request-ID": unsafe_request_id},
    )

    replacement = response.headers["X-Request-ID"]
    assert replacement != unsafe_request_id
    assert REQUEST_ID_PATTERN.fullmatch(replacement)


@pytest.mark.parametrize("path", ["/health/live", "/missing", "/docs"])
def test_every_http_response_has_request_id(
    client: TestClient,
    path: str,
) -> None:
    response = client.get(path)

    assert REQUEST_ID_PATTERN.fullmatch(response.headers["X-Request-ID"])


def test_middleware_overwrites_route_supplied_request_id(
    test_settings: Settings,
) -> None:
    application = create_app(test_settings)

    @application.get("/_test/header")
    async def header_response() -> Response:
        return Response(headers={"X-Request-ID": "route-controlled"})

    with TestClient(application) as test_client:
        response = test_client.get(
            "/_test/header",
            headers={"X-Request-ID": "trusted-client-id"},
        )

    assert response.headers["X-Request-ID"] == "trusted-client-id"


def test_request_id_is_bound_only_during_request(
    test_settings: Settings,
) -> None:
    application = create_app(test_settings)

    @application.get("/_test/context")
    async def context_response() -> dict[str, str | None]:
        return {"request_id": get_request_id()}

    assert get_request_id() is None
    with TestClient(application) as test_client:
        response = test_client.get("/_test/context")

    assert response.json() == {
        "request_id": response.headers["X-Request-ID"],
    }
    assert get_request_id() is None


def test_configure_logging_disables_uvicorn_access_logger() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.disabled = False

    configure_logging()

    assert access_logger.disabled is True


def test_request_log_contains_metadata_but_not_body(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="falcon_api.http")
    falcon_logger = logging.getLogger("falcon_api")
    falcon_logger.addHandler(caplog.handler)
    try:
        response = client.post(
            "/health/live?ignored=TOP-SECRET-QUERY",
            content="TOP-SECRET-BODY",
            headers={"X-Request-ID": "log-correlation-id"},
        )
    finally:
        falcon_logger.removeHandler(caplog.handler)

    record = next(
        record
        for record in caplog.records
        if record.name == "falcon_api.http"
        and getattr(record, "request_id", None) == "log-correlation-id"
    )
    assert response.status_code == 405
    assert record.http_method == "POST"
    assert record.http_path == "/health/live"
    assert record.http_status == 405
    assert record.duration_ms >= 0
    rendered_record = JsonLogFormatter().format(record)
    assert "TOP-SECRET-BODY" not in caplog.text
    assert "TOP-SECRET-QUERY" not in caplog.text
    assert "TOP-SECRET-BODY" not in rendered_record
    assert "TOP-SECRET-QUERY" not in rendered_record


def test_request_id_helpers_restore_nested_context() -> None:
    generated = resolve_request_id(None)

    assert re.fullmatch(r"[0-9a-f]{32}", generated)
    with bind_request_id("outer"):
        assert get_request_id() == "outer"
        with bind_request_id("inner"):
            assert get_request_id() == "inner"
        assert get_request_id() == "outer"
    assert get_request_id() is None
