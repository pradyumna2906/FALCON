"""Unified API error-contract tests."""

import logging
from datetime import datetime
from typing import Annotated, Any

import pytest
from falcon_api.core.config import Settings
from falcon_api.core.errors import ApplicationError
from falcon_api.core.logging import JsonLogFormatter
from falcon_api.main import create_app
from fastapi import HTTPException, Query
from fastapi.testclient import TestClient


def assert_common_error(
    response: Any,
    *,
    status_code: int,
    code: str,
    message: str,
) -> dict[str, object]:
    assert response.status_code == status_code
    payload = response.json()
    error = payload["error"]
    assert error["code"] == code
    assert error["message"] == message
    assert error["request_id"] == response.headers["X-Request-ID"]
    assert datetime.fromisoformat(error["timestamp"]).tzinfo is not None
    return error


def test_not_found_uses_common_error_envelope(client: TestClient) -> None:
    response = client.get(
        "/not-found",
        headers={"X-Request-ID": "not-found-id"},
    )

    error = assert_common_error(
        response,
        status_code=404,
        code="not_found",
        message="Not Found.",
    )
    assert set(error) == {"code", "message", "request_id", "timestamp"}


def test_method_not_allowed_preserves_allow_header(client: TestClient) -> None:
    response = client.post("/health/live")

    assert_common_error(
        response,
        status_code=405,
        code="method_not_allowed",
        message="Method Not Allowed.",
    )
    assert response.headers["allow"] == "GET"


def test_custom_http_detail_and_headers_are_not_reflected(
    test_settings: Settings,
) -> None:
    application = create_app(test_settings)

    @application.get("/_test/http-error")
    async def http_error() -> None:
        raise HTTPException(
            status_code=400,
            detail="account-token=TOP-SECRET",
            headers={"X-Internal-Configuration": "TOP-SECRET-HEADER"},
        )

    with TestClient(application) as test_client:
        response = test_client.get("/_test/http-error")

    assert_common_error(
        response,
        status_code=400,
        code="bad_request",
        message="Bad Request.",
    )
    assert "TOP-SECRET" not in response.text
    assert "x-internal-configuration" not in response.headers
    assert "TOP-SECRET-HEADER" not in str(response.headers)


def test_nonstandard_http_status_uses_generic_contract(
    test_settings: Settings,
) -> None:
    application = create_app(test_settings)

    @application.get("/_test/nonstandard")
    async def nonstandard_error() -> None:
        raise HTTPException(status_code=499, detail="private detail")

    with TestClient(application) as test_client:
        response = test_client.get("/_test/nonstandard")

    assert_common_error(
        response,
        status_code=499,
        code="http_error",
        message="The HTTP request failed.",
    )


def test_known_application_error_uses_public_contract(
    test_settings: Settings,
) -> None:
    application = create_app(test_settings)

    @application.get("/_test/application-error")
    async def application_error() -> None:
        raise ApplicationError(
            code="goal_conflict",
            message="The selected goals conflict.",
            status_code=409,
        )

    with TestClient(application) as test_client:
        response = test_client.get("/_test/application-error")

    assert_common_error(
        response,
        status_code=409,
        code="goal_conflict",
        message="The selected goals conflict.",
    )


def test_validation_error_excludes_rejected_value(
    test_settings: Settings,
) -> None:
    application = create_app(test_settings)

    @application.get("/_test/validation")
    async def validation(
        limit: Annotated[int, Query(gt=0)],
    ) -> dict[str, int]:
        return {"limit": limit}

    with TestClient(application) as test_client:
        response = test_client.get(
            "/_test/validation?limit=TOP-SECRET-VALUE",
        )

    error = assert_common_error(
        response,
        status_code=422,
        code="validation_error",
        message="Request validation failed.",
    )
    assert error["details"] == [
        {
            "field": "query.limit",
            "message": "Value has an invalid format.",
        },
    ]
    assert "TOP-SECRET-VALUE" not in response.text
    assert "input" not in response.text


def test_unexpected_error_is_generic_and_correlated(
    test_settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    application = create_app(test_settings)

    @application.get("/_test/unexpected")
    async def unexpected() -> None:
        raise RuntimeError("database-password=TOP-SECRET")

    caplog.set_level(logging.ERROR)
    falcon_logger = logging.getLogger("falcon_api")
    falcon_logger.addHandler(caplog.handler)
    try:
        with TestClient(
            application,
            raise_server_exceptions=False,
        ) as test_client:
            response = test_client.get(
                "/_test/unexpected",
                headers={"X-Request-ID": "unexpected-error-id"},
            )
    finally:
        falcon_logger.removeHandler(caplog.handler)

    assert_common_error(
        response,
        status_code=500,
        code="internal_server_error",
        message="An unexpected error occurred.",
    )
    assert "TOP-SECRET" not in response.text
    assert "TOP-SECRET" not in caplog.text
    error_record = next(
        record
        for record in caplog.records
        if record.name == "falcon_api.errors"
    )
    rendered_record = JsonLogFormatter().format(error_record)
    assert error_record.error_type == "RuntimeError"
    assert error_record.request_id == "unexpected-error-id"
    assert "TOP-SECRET" not in rendered_record
    assert "RuntimeError" in rendered_record
    assert "unexpected-error-id" in rendered_record


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {"code": "Invalid-Code", "message": "safe", "status_code": 400},
            "stable snake_case",
        ),
        (
            {"code": "valid_code", "message": "safe", "status_code": 200},
            "between 400 and 599",
        ),
    ],
)
def test_application_error_rejects_invalid_contract(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ApplicationError(**kwargs)  # type: ignore[arg-type]
