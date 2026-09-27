"""Real-API onboarding, import, correction, dashboard and session lifecycle."""

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from falcon_api.core.config import Settings
from falcon_api.core.event_loop import create_psycopg_compatible_event_loop
from falcon_api.main import create_app
from fastapi.testclient import TestClient

from .verification import verify_registered_user

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("FALCON_RUN_DATABASE_INTEGRATION") != "1",
        reason="Requires an explicitly enabled PostgreSQL service.",
    ),
]


def test_verified_onboarding_import_correction_dashboard_and_logout():
    root = Path(__file__).resolve().parents[3]
    command.upgrade(Config(str(root / "backend/alembic.ini")), "head")
    settings = Settings(_env_file=root / ".env", env="test")
    user_ids = []
    today = datetime.now(UTC).date().isoformat()
    password = "Synthetic-Frontend-Password-2026!"
    try:
        with TestClient(
            create_app(settings),
            backend_options={"loop_factory": create_psycopg_compatible_event_loop},
        ) as client:
            email = f"frontend-{uuid4().hex}@example.com"
            registered = client.post(
                "/api/v1/auth/register",
                json={
                    "email": email,
                    "password": password,
                    "timezone": "UTC",
                    "default_currency": "INR",
                },
            )
            assert registered.status_code == 201, registered.text
            user_ids.append(UUID(registered.json()["id"]))
            login = client.post(
                "/api/v1/auth/login", json={"email": email, "password": password}
            )
            assert login.status_code == 200
            headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            assert client.get("/api/v1/accounts", headers=headers).status_code == 403
            assert (
                client.get("/api/v1/auth/me", headers=headers).json()["email_verified"]
                is False
            )
            verify_registered_user(client, user_ids[0])
            assert (
                client.get("/api/v1/auth/me", headers=headers).json()["email_verified"]
                is True
            )
            profile = client.put(
                "/api/v1/profile",
                headers=headers,
                json={
                    "income_pattern": "salaried",
                    "income_stability": "stable",
                    "has_household_responsibilities": False,
                    "dependant_count": 0,
                    "emergency_fund_target_months": "6",
                },
            )
            assert profile.status_code == 201, profile.text
            account = client.post(
                "/api/v1/accounts",
                headers=headers,
                json={
                    "name": "Synthetic bank",
                    "account_type": "bank",
                    "currency": "INR",
                    "opening_balance": "0",
                    "opening_balance_date": today,
                },
            )
            assert account.status_code == 201, account.text
            account_id = account.json()["id"]
            statement = f"Date,Description,Amount,Reference\n{today},Synthetic groceries,-123.4567,ROW1\n{today},Invalid row,0,ROW2\n".encode()
            imported = client.post(
                "/api/v1/imports",
                headers=headers,
                data={
                    "account_id": account_id,
                    "source_type": "csv",
                    "date_order": "year_first",
                    "header_row": "1",
                },
                files={"file": ("synthetic.csv", statement, "text/csv")},
            )
            assert imported.status_code == 201, imported.text
            assert imported.json()["accepted_count"] == 1
            assert imported.json()["rejected_count"] == 1
            history = client.get("/api/v1/imports?limit=10", headers=headers)
            assert history.status_code == 200, history.text
            assert history.json()["items"][0]["id"] == imported.json()["id"]
            rows = client.get("/api/v1/transactions?limit=25", headers=headers).json()[
                "items"
            ]
            assert len(rows) == 1
            categories = client.get("/api/v1/categories", headers=headers).json()[
                "items"
            ]
            category = next(
                item
                for item in categories
                if item["kind"] == "expense" and item["classification_code"]
            )
            correction = client.post(
                f"/api/v1/transactions/{rows[0]['id']}/classification/correction",
                headers=headers,
                json={"category_id": category["id"]},
            )
            assert correction.status_code == 200, correction.text
            memory = client.put(
                "/api/v1/classification/merchant-memories",
                headers=headers,
                json={
                    "merchant_name": "Synthetic groceries",
                    "category_id": category["id"],
                },
            )
            assert memory.status_code == 200, memory.text
            dashboard = client.get(
                f"/api/v1/analytics/dashboard?date_from={today}&date_to={today}&currency=INR",
                headers=headers,
            )
            assert dashboard.status_code == 200, dashboard.text
            assert dashboard.json()["metrics"]["total_expense"]["value"] == "123.4567"
            assert (
                dashboard.json()["context"]["completeness"][
                    "eligible_transaction_count"
                ]
                == 1
            )
            refresh = client.post("/api/v1/auth/refresh")
            assert refresh.status_code == 200
            fresh_headers = {
                "Authorization": f"Bearer {refresh.json()['access_token']}"
            }
            assert (
                client.get("/api/v1/auth/me", headers=fresh_headers).status_code == 200
            )
            assert client.post("/api/v1/auth/logout").status_code == 204
            assert (
                client.get("/api/v1/accounts", headers=fresh_headers).status_code == 401
            )
            assert client.post("/api/v1/auth/refresh").status_code == 401
    finally:
        if user_ids:
            with psycopg.connect(
                host=settings.db_host,
                port=settings.db_port,
                dbname=settings.db_name,
                user=settings.db_user,
                password=settings.db_password.get_secret_value(),
                connect_timeout=settings.db_connect_timeout_seconds,
            ) as connection:
                connection.execute("DELETE FROM users WHERE id = ANY(%s)", (user_ids,))
