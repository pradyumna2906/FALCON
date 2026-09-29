"""Consolidated security contracts for the completed authentication API."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


_AUTHENTICATION_PATHS = {
    "/api/v1/auth/register",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/auth/logout",
    "/api/v1/auth/email-verification/request",
    "/api/v1/auth/email-verification/confirm",
    "/api/v1/auth/password-reset/request",
    "/api/v1/auth/password-reset/confirm",
    "/api/v1/auth/me",
}

_EXPECTED_OPERATIONS = {
    "/api/v1/auth/register": "post",
    "/api/v1/auth/login": "post",
    "/api/v1/auth/refresh": "post",
    "/api/v1/auth/logout": "post",
    "/api/v1/auth/email-verification/request": "post",
    "/api/v1/auth/email-verification/confirm": "post",
    "/api/v1/auth/password-reset/request": "post",
    "/api/v1/auth/password-reset/confirm": "post",
    "/api/v1/auth/me": "get",
}

_TRUSTED_ORIGIN = "https://app.falcon.test"
_UNTRUSTED_ORIGIN = "https://untrusted.example"
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_COMPLETION_DOCUMENT = (
    _REPOSITORY_ROOT
    / "docs"
    / "authentication"
    / "PHASE_3_IMPLEMENTATION.md"
)


def test_openapi_exposes_the_complete_authentication_surface(
    client: TestClient,
) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    authentication_paths = {
        path
        for path in paths
        if path.startswith("/api/v1/auth/")
    }

    assert authentication_paths == _AUTHENTICATION_PATHS

    for path, method in _EXPECTED_OPERATIONS.items():
        assert set(paths[path]) == {method}


def test_only_current_user_requires_openapi_bearer_security(
    client: TestClient,
) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert paths["/api/v1/auth/me"]["get"]["security"] == [
        {"HTTPBearer": []}
    ]

    for path in _AUTHENTICATION_PATHS - {"/api/v1/auth/me"}:
        operation = paths[path][_EXPECTED_OPERATIONS[path]]
        assert operation.get("security", []) == []


def test_current_user_response_excludes_sensitive_material(
    client: TestClient,
) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    current_user = schemas["CurrentUserResponse"]
    properties = set(current_user["properties"])

    assert properties == {
        "id",
        "email",
        "display_name",
        "timezone",
        "default_currency",
        "email_verified",
    }

    forbidden_names = {
        "password",
        "password_hash",
        "access_token",
        "refresh_token",
        "token",
        "session_id",
        "family_id",
    }

    assert properties.isdisjoint(forbidden_names)


def test_cookie_authenticated_routes_do_not_accept_request_tokens(
    client: TestClient,
) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    for path in (
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
    ):
        operation = paths[path]["post"]
        assert "requestBody" not in operation
        assert operation.get("parameters", []) == []


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/api/v1/auth/refresh",
            None,
        ),
        (
            "/api/v1/auth/logout",
            None,
        ),
        (
            "/api/v1/auth/password-reset/confirm",
            {
                "token": "a" * 43,
                "new_password": (
                    "New-Correct-Horse-Battery-Staple-2026!"
                ),
            },
        ),
    ],
)
def test_browser_credential_mutations_reject_untrusted_origins(
    client: TestClient,
    path: str,
    payload: dict[str, str] | None,
) -> None:
    response = client.post(
        path,
        headers={"Origin": _UNTRUSTED_ORIGIN},
        json=payload,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_not_allowed"


def test_trusted_origin_is_not_rejected_by_origin_policy(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/auth/refresh",
        headers={"Origin": _TRUSTED_ORIGIN},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == (
        "invalid_refresh_session"
    )


def test_authentication_completion_document_declares_boundaries() -> None:
    content = _COMPLETION_DOCUMENT.read_text(
        encoding="utf-8"
    ).lower()

    required_statements = (
        "phase 3 status: complete",
        "distributed rate limiting",
        "external email provider",
        "oauth",
        "mfa",
        "not implemented",
    )

    for statement in required_statements:
        assert statement in content
