"""Initial API endpoint tests."""

from fastapi.testclient import TestClient


def test_liveness_is_dependency_free(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "falcon-api"}


def test_api_v1_index_identifies_boundary(client: TestClient) -> None:
    response = client.get("/api/v1")

    assert response.status_code == 200
    assert response.json() == {"service": "falcon-api", "api_version": "v1"}


def test_liveness_does_not_accept_post(client: TestClient) -> None:
    assert client.post("/health/live").status_code == 405
