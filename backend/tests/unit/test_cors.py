"""Trusted browser-origin policy tests."""

import logging

import pytest
from falcon_api.core.logging import JsonLogFormatter
from fastapi.testclient import TestClient


TRUSTED_ORIGIN = "https://app.falcon.test"
UNTRUSTED_ORIGIN = "https://untrusted.example"


def test_trusted_origin_receives_explicit_cors_headers(
    client: TestClient,
) -> None:
    response = client.get(
        "/health/live",
        headers={"Origin": TRUSTED_ORIGIN},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == TRUSTED_ORIGIN
    assert response.headers["access-control-expose-headers"] == "X-Request-ID"
    assert "access-control-allow-credentials" not in response.headers
    assert response.headers["vary"] == "Origin"


def test_untrusted_origin_is_not_authorized_or_blocked_by_application(
    client: TestClient,
) -> None:
    response = client.get(
        "/health/live",
        headers={"Origin": UNTRUSTED_ORIGIN},
    )

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-credentials" not in response.headers
    assert "X-Request-ID" in response.headers


def test_trusted_preflight_is_limited_correlated_and_logged(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    request_id = "cors-preflight-id"
    caplog.set_level(logging.INFO, logger="falcon_api.http")
    falcon_logger = logging.getLogger("falcon_api")
    falcon_logger.addHandler(caplog.handler)
    try:
        response = client.options(
            "/health/live",
            headers={
                "Origin": TRUSTED_ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Content-Type, X-Request-ID",
                "X-Request-ID": request_id,
            },
        )
    finally:
        falcon_logger.removeHandler(caplog.handler)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == TRUSTED_ORIGIN
    assert response.headers["access-control-allow-methods"] == "GET, POST"
    allowed_headers = {
        header.strip().lower()
        for header in response.headers["access-control-allow-headers"].split(",")
    }
    assert allowed_headers == {
        "accept",
        "accept-language",
        "content-language",
        "content-type",
        "x-request-id",
    }
    assert "access-control-allow-credentials" not in response.headers
    assert response.headers["X-Request-ID"] == request_id

    record = next(
        record
        for record in caplog.records
        if record.name == "falcon_api.http"
        and getattr(record, "request_id", None) == request_id
    )
    assert record.http_method == "OPTIONS"
    assert record.http_path == "/health/live"
    assert record.http_status == 200
    assert request_id in JsonLogFormatter().format(record)


@pytest.mark.parametrize(
    "preflight_headers",
    [
        {
            "Origin": TRUSTED_ORIGIN,
            "Access-Control-Request-Method": "DELETE",
        },
        {
            "Origin": TRUSTED_ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
        {
            "Origin": UNTRUSTED_ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    ],
)
def test_disallowed_preflight_is_rejected_without_origin_authorization(
    client: TestClient,
    preflight_headers: dict[str, str],
) -> None:
    response = client.options("/health/live", headers=preflight_headers)

    assert response.status_code == 400
    if preflight_headers["Origin"] == UNTRUSTED_ORIGIN:
        assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-credentials" not in response.headers
    assert "X-Request-ID" in response.headers
