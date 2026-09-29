"""Every financial API enforces verification before parsing financial inputs."""

import re
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from falcon_api.api.routes.auth import current_principal
from falcon_api.infrastructure.database import get_database_session


def test_all_financial_routes_reject_unverified_identity(client):
    owner = SimpleNamespace(user_id=uuid4(), email_verified_at=None)

    async def session():
        yield AsyncMock()

    client.app.dependency_overrides[current_principal] = lambda: owner
    client.app.dependency_overrides[get_database_session] = session
    try:
        checked = 0
        for route, operations in client.app.openapi()["paths"].items():
            if not route.startswith("/api/v1/") or route.startswith("/api/v1/auth/"):
                continue
            path = re.sub(r"\{[^}]+\}", lambda _: str(uuid4()), route)
            for method in operations:
                response = client.request(method, path)
                assert response.status_code == 403, (method, path, response.text)
                assert response.json()["error"]["code"] == "email_verification_required"
                checked += 1
        assert checked >= 70
    finally:
        client.app.dependency_overrides.clear()


def test_verified_gate_returns_same_principal():
    from falcon_api.api.routes.setup import verified_principal

    owner = SimpleNamespace(user_id=uuid4(), email_verified_at=datetime.now(UTC))
    assert verified_principal(owner) is owner
