"""Exercise Batch 3 API workflows with real history, forecasts and goal plans."""

import os
from datetime import UTC, date, datetime, timedelta
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


def _month(start: date, offset: int) -> date:
    year, month = divmod(start.year * 12 + start.month - 1 + offset, 12)
    return date(year, month + 1, 1)


def test_transaction_history_forecasts_goal_contributions_and_plan_lifecycle():
    root = Path(__file__).resolve().parents[3]
    command.upgrade(Config(str(root / "backend/alembic.ini")), "head")
    settings = Settings(_env_file=root / ".env", env="test")
    user_ids = []
    today = datetime.now(UTC).date()
    month = today.replace(day=1)
    history_start, history_end = _month(month, -12), month - timedelta(days=1)
    password = "Synthetic-Planning-Password-2026!"
    try:
        with TestClient(
            create_app(settings),
            base_url="https://testserver",
            backend_options={"loop_factory": create_psycopg_compatible_event_loop},
        ) as client:
            def register():
                email = f"planning-{uuid4().hex}@example.com"
                created = client.post("/api/v1/auth/register", json={
                    "email": email, "password": password,
                    "timezone": "UTC", "default_currency": "INR",
                })
                assert created.status_code == 201, created.text
                user_ids.append(UUID(created.json()["id"]))
                verify_registered_user(client, user_ids[-1])
                login = client.post("/api/v1/auth/login", json={
                    "email": email, "password": password,
                })
                assert login.status_code == 200, login.text
                return {"Authorization": f"Bearer {login.json()['access_token']}"}

            headers = register()

            def request(method, path, expected=200, **kwargs):
                response = client.request(method, "/api/v1" + path, headers=headers, **kwargs)
                assert response.status_code == expected, response.text
                return response.json() if expected != 204 else None

            request("PUT", "/profile", 201, json={
                "income_pattern": "salaried", "income_stability": "stable",
                "has_household_responsibilities": False, "dependant_count": 0,
                "emergency_fund_target_months": "1",
            })
            account = request("POST", "/accounts", 201, json={
                "name": "Synthetic planning bank", "account_type": "bank",
                "currency": "INR", "opening_balance": "0",
                "opening_balance_date": history_start.isoformat(),
            })
            forecast_payload = {
                "target": "savings_amount", "granularity": "month", "currency": "INR",
                "history_start": history_start.isoformat(),
                "history_end": history_end.isoformat(), "horizon": 6,
            }
            request("POST", "/forecasts", 422, json=forecast_payload)
            rows = ["Date,Description,Amount,Reference"]
            for index in range(12):
                period = _month(history_start, index).isoformat()
                rows.extend([
                    f"{period},Synthetic income,10000.1234,IN-{index}",
                    f"{period},Synthetic expense,-2000.0000,OUT-{index}",
                ])
            imported = request("POST", "/imports", 201,
                data={"account_id": account["id"], "source_type": "csv", "date_order": "year_first", "header_row": "1"},
                files={"file": ("planning.csv", "\n".join(rows).encode(), "text/csv")},
            )
            assert imported["accepted_count"] == 24
            assert imported["rejected_count"] == 0
            forecasts = {}
            for target in ("gross_income", "total_expense", "net_cash_flow", "savings_amount"):
                forecasts[target] = request("POST", "/forecasts", 201, json={**forecast_payload, "target": target})
                run = forecasts[target]
                assert len(run["points"]) == 6
                assert request("GET", f"/forecasts/{run['id']}")["points"] == run["points"]
            savings = forecasts["savings_amount"]
            assert savings["points"][0]["expected_value"] == "8000.1234"
            assert len(request("GET", "/forecasts?limit=20")["items"]) == 4
            for endpoint in ("cash-flow", "spending", "recurring", "spending-signals", "health-score", "insights"):
                analytics = request("GET", f"/analytics/{endpoint}", params={
                    "date_from": history_start.isoformat(), "date_to": history_end.isoformat(), "currency": "INR",
                })
                assert analytics["context"]["currency"] == "INR"
                assert analytics["context"]["completeness"]["eligible_transaction_count"] == 24
            budget = request("POST", "/budgets", 201, json={
                "name": "Planning budget", "currency": "INR", "overall_limit": "2000",
                "period_start_date": month.isoformat(),
                "period_end_date": (_month(month, 1) - timedelta(days=1)).isoformat(), "limits": [],
            })
            request("GET", f"/analytics/budgets/{budget['id']}")
            goal = request("POST", "/goals", 201, json={
                "name": "Trip fund", "goal_type": "travel", "target_amount": "1000.1234",
                "starting_amount": "0", "currency": "INR", "priority": "high",
                "target_date": _month(month, 4).isoformat(),
            })
            goal_id = goal["id"]
            request("PATCH", f"/goals/{goal_id}", json={"description": "Synthetic trip"})
            contribution = request("POST", f"/goals/{goal_id}/contributions", 201, json={
                "source_type": "manual", "amount": "25.1234", "contribution_date": today.isoformat(),
            })
            progress = request("GET", f"/goals/{goal_id}/progress")
            assert progress["current_amount"] == "25.1234"
            assert progress["remaining_amount"] == "975.0000"
            snapshot = request("GET", "/goal-planning/snapshot?currency=INR")
            assert snapshot["provenance"]["forecast_run_id"] == savings["id"]
            plan = request("POST", "/goal-plans", 201, json={"currency": "INR"})
            assert plan["strategy"] != "blocked"
            assert plan["outcomes"][0]["goal_id"] == goal_id
            assert plan["forecast_run_id"] == savings["id"]
            approved = request("POST", f"/goal-plans/{plan['id']}/approve")
            assert approved["status"] == "approved"
            regenerated = request("POST", f"/goal-plans/{plan['id']}/regenerate", 201)
            assert regenerated["predecessor_plan_id"] == plan["id"]
            assert request("GET", f"/goal-plans/{plan['id']}")["status"] == "superseded"
            assert request("POST", f"/goal-plans/{regenerated['id']}/reject")["status"] == "rejected"
            request("POST", f"/goal-plans/{regenerated['id']}/regenerate", 409)
            assert len(request("GET", "/goal-plans?limit=20")["items"]) == 2
            request("DELETE", f"/goals/{goal_id}/contributions/{contribution['id']}", 204)
            assert request("GET", f"/goals/{goal_id}/progress")["current_amount"] == "0.0000"
            assert request("POST", f"/goals/{goal_id}/cancel")["status"] == "cancelled"

            foreign = register()
            for path in (f"/forecasts/{savings['id']}", f"/goal-plans/{plan['id']}", f"/goals/{goal_id}/progress"):
                response = client.get("/api/v1" + path, headers=foreign)
                assert response.status_code == 404, response.text
            assert client.get("/api/v1/forecasts", headers=foreign).json()["items"] == []
            assert client.get("/api/v1/goal-plans", headers=foreign).json()["items"] == []
    finally:
        if user_ids:
            with psycopg.connect(
                host=settings.db_host, port=settings.db_port, dbname=settings.db_name,
                user=settings.db_user, password=settings.db_password.get_secret_value(),
                connect_timeout=settings.db_connect_timeout_seconds,
            ) as connection:
                connection.execute("DELETE FROM users WHERE id = ANY(%s)", (user_ids,))
