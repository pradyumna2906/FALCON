"""Real PostgreSQL classification persistence, API, and isolation tests."""

import os
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from falcon_api.core.config import AppEnvironment, Settings
from falcon_api.core.event_loop import create_psycopg_compatible_event_loop
from falcon_api.main import create_app
from fastapi.testclient import TestClient


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("FALCON_RUN_DATABASE_INTEGRATION") != "1",
        reason="Set FALCON_RUN_DATABASE_INTEGRATION=1 to enable these tests.",
    ),
]

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_CONFIG = _REPOSITORY_ROOT / "backend" / "alembic.ini"
_PASSWORD = "Classification-Integration-Password-2026!"


def integration_settings() -> Settings:
    """Load ignored local PostgreSQL settings with deterministic API behavior."""
    return Settings(
        _env_file=_REPOSITORY_ROOT / ".env",
        env=AppEnvironment.TEST,
        debug=False,
        docs_enabled=False,
        cors_allowed_origins=(),
    )


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[None]:
    """Ensure classification tests run against the migration head."""
    command.upgrade(Config(str(_ALEMBIC_CONFIG)), "head")
    yield


def _register_login_and_account(
    client: TestClient,
    *,
    email: str,
) -> tuple[UUID, str, UUID]:
    registration = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": _PASSWORD,
            "timezone": "Asia/Kolkata",
            "default_currency": "INR",
        },
    )
    assert registration.status_code == 201, registration.text
    user_id = UUID(registration.json()["id"])
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": _PASSWORD},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    account = client.post(
        "/api/v1/accounts",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": f"Classification {uuid4().hex[:8]}",
            "account_type": "bank",
            "opening_balance": "10000.0000",
            "opening_balance_date": date.today().isoformat(),
        },
    )
    assert account.status_code == 201, account.text
    return user_id, token, UUID(account.json()["id"])


def _create_transaction(
    client: TestClient,
    *,
    token: str,
    account_id: UUID,
    merchant: str,
) -> UUID:
    response = client.post(
        "/api/v1/transactions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "account_id": str(account_id),
            "category_id": None,
            "transaction_type": "expense",
            "amount": "825.0000",
            "transaction_date": date.today().isoformat(),
            "description": f"UPI {merchant} order",
            "merchant_name": merchant,
        },
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


def test_rule_assignment_is_atomic_idempotent_and_owner_isolated() -> None:
    """Persist an automatic rule result and reject a mixed-owner batch."""
    settings = integration_settings()
    email_a = f"classification-a-{uuid4().hex}@example.com"
    email_b = f"classification-b-{uuid4().hex}@example.com"
    user_ids: list[UUID] = []

    try:
        with TestClient(
            create_app(settings),
            backend_options={
                "loop_factory": create_psycopg_compatible_event_loop,
            },
        ) as client:
            user_a, token_a, account_a = _register_login_and_account(
                client, email=email_a
            )
            user_b, token_b, account_b = _register_login_and_account(
                client, email=email_b
            )
            user_ids.extend((user_a, user_b))
            transaction_a = _create_transaction(
                client,
                token=token_a,
                account_id=account_a,
                merchant="Swiggy",
            )
            transaction_b = _create_transaction(
                client,
                token=token_b,
                account_id=account_b,
                merchant="Swiggy",
            )
            headers_a = {"Authorization": f"Bearer {token_a}"}

            classified = client.post(
                f"/api/v1/transactions/{transaction_a}/classification",
                headers=headers_a,
            )
            assert classified.status_code == 200, classified.text
            assert classified.json()["decision"] == "automatic"
            assert classified.json()["source"] == "rule"
            assert classified.json()["subcategory_code"] == "food_delivery"

            repeated = client.post(
                f"/api/v1/transactions/{transaction_a}/classification",
                headers=headers_a,
            )
            assert repeated.status_code == 200, repeated.text
            assert repeated.json() == classified.json()

            transaction = client.get(
                f"/api/v1/transactions/{transaction_a}", headers=headers_a
            )
            assert transaction.status_code == 200, transaction.text
            category_id = transaction.json()["category_id"]
            assert category_id is not None
            categories = client.get("/api/v1/categories", headers=headers_a)
            matching = [
                item
                for item in categories.json()["items"]
                if item["classification_code"] == "food_delivery"
            ]
            assert len(matching) == 1
            assert matching[0]["id"] == category_id

            pending_a = _create_transaction(
                client,
                token=token_a,
                account_id=account_a,
                merchant="Swiggy",
            )
            denied = client.post(
                "/api/v1/classifications/batch",
                headers=headers_a,
                json={
                    "transaction_ids": [str(pending_a), str(transaction_b)]
                },
            )
            assert denied.status_code == 404, denied.text
            assert denied.json()["error"]["code"] == "transaction_not_found"
            untouched = client.get(
                f"/api/v1/transactions/{pending_a}", headers=headers_a
            )
            assert untouched.json()["category_id"] is None
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
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM users WHERE id = ANY(%s)",
                        (user_ids,),
                    )


def test_corrections_are_immutable_and_merchant_memory_is_user_isolated() -> None:
    """Exercise trusted correction snapshots and exact memory through the API."""
    settings = integration_settings()
    email_a = f"personalization-a-{uuid4().hex}@example.com"
    email_b = f"personalization-b-{uuid4().hex}@example.com"
    user_ids: list[UUID] = []

    try:
        with TestClient(
            create_app(settings),
            backend_options={
                "loop_factory": create_psycopg_compatible_event_loop,
            },
        ) as client:
            user_a, token_a, account_a = _register_login_and_account(
                client, email=email_a
            )
            user_b, token_b, _ = _register_login_and_account(
                client, email=email_b
            )
            user_ids.extend((user_a, user_b))
            headers_a = {"Authorization": f"Bearer {token_a}"}
            headers_b = {"Authorization": f"Bearer {token_b}"}
            categories = client.get(
                "/api/v1/categories", headers=headers_a
            ).json()["items"]
            category_by_code = {
                item["classification_code"]: item
                for item in categories
                if item["classification_code"] is not None
            }

            saved_memory = client.put(
                "/api/v1/classification/merchant-memories",
                headers=headers_a,
                json={
                    "merchant_name": "Corner Boutique",
                    "category_id": category_by_code["groceries"]["id"],
                },
            )
            assert saved_memory.status_code == 200, saved_memory.text
            memory_id = saved_memory.json()["id"]
            assert saved_memory.json()["normalized_merchant"] == (
                "corner boutique"
            )

            classified_from_memory = _create_transaction(
                client,
                token=token_a,
                account_id=account_a,
                merchant="Corner Boutique",
            )
            classified = client.post(
                f"/api/v1/transactions/{classified_from_memory}/classification",
                headers=headers_a,
            )
            assert classified.status_code == 200, classified.text
            assert classified.json()["source"] == "merchant_memory"
            assert classified.json()["subcategory_code"] == "groceries"

            foreign_list = client.get(
                "/api/v1/classification/merchant-memories",
                headers=headers_b,
            )
            assert foreign_list.status_code == 200, foreign_list.text
            assert foreign_list.json()["items"] == []
            foreign_delete = client.delete(
                f"/api/v1/classification/merchant-memories/{memory_id}",
                headers=headers_b,
            )
            assert foreign_delete.status_code == 404, foreign_delete.text

            swiggy = _create_transaction(
                client,
                token=token_a,
                account_id=account_a,
                merchant="Swiggy",
            )
            predicted = client.post(
                f"/api/v1/transactions/{swiggy}/classification",
                headers=headers_a,
            )
            assert predicted.status_code == 200, predicted.text
            corrected = client.post(
                f"/api/v1/transactions/{swiggy}/classification/correction",
                headers=headers_a,
                json={
                    "category_id": category_by_code["restaurants"]["id"]
                },
            )
            assert corrected.status_code == 201, corrected.text
            assert corrected.json()["original"] == predicted.json()
            transaction = client.get(
                f"/api/v1/transactions/{swiggy}", headers=headers_a
            )
            assert transaction.json()["category_id"] == (
                category_by_code["restaurants"]["id"]
            )
            assert transaction.json()["is_user_modified"] is True

            correction_id = UUID(corrected.json()["id"])
            with psycopg.connect(
                host=settings.db_host,
                port=settings.db_port,
                dbname=settings.db_name,
                user=settings.db_user,
                password=settings.db_password.get_secret_value(),
                connect_timeout=settings.db_connect_timeout_seconds,
            ) as connection:
                with connection.cursor() as cursor:
                    with pytest.raises(psycopg.errors.RaiseException):
                        cursor.execute(
                            "UPDATE transaction_category_corrections "
                            "SET original_confidence = 0 "
                            "WHERE id = %s",
                            (correction_id,),
                        )
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
                with connection.cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM users WHERE id = ANY(%s)",
                        (user_ids,),
                    )
