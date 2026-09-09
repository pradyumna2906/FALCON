"""Real PostgreSQL analytics aggregation and owner-isolation tests."""

import asyncio
import os
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from falcon_api.analytics import (
    ANALYTICS_DASHBOARD_PERFORMANCE_BUDGET_SECONDS,
    AnalyticsGranularity,
    AnalyticsPeriod,
    AnalyticsRepository,
)
from falcon_api.analytics.application import (
    AnalyticsSelection,
    FinancialAnalyticsService,
)
from falcon_api.analytics.semantics import AnalyticsComparisonMode
from falcon_api.core.config import AppEnvironment, Settings
from falcon_api.core.event_loop import create_psycopg_compatible_event_loop
from falcon_api.forecasting import (
    ForecastGranularity as ForecastBucketGranularity,
    ForecastHistoryWindow,
    ForecastPersistenceRepository,
    ForecastPointWrite,
    ForecastRunWrite,
    ForecastTarget,
    ForecastingRepository,
    build_forecast_series,
)
from falcon_api.infrastructure.database import create_database_resources
from falcon_api.infrastructure.persistence import transaction_scope
from falcon_api.main import create_app
from falcon_api.models.account import Account
from falcon_api.models.category import Category
from falcon_api.models.enums import (
    AccountType,
    CategoryKind,
    TransactionSourceType,
    TransactionStatus,
    TransactionType,
    UserStatus,
)
from falcon_api.models.forecasting import ForecastRun
from falcon_api.models.ledger import Transaction, TransferGroup
from falcon_api.models.planning import Budget, BudgetLimit
from falcon_api.models.user import User
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, update
from sqlalchemy.exc import DBAPIError

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("FALCON_RUN_DATABASE_INTEGRATION") != "1",
        reason="Set FALCON_RUN_DATABASE_INTEGRATION=1 to enable these tests.",
    ),
]

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_CONFIG = _REPOSITORY_ROOT / "backend" / "alembic.ini"
_NOW = datetime(2026, 8, 24, 8, tzinfo=UTC)
_PERIOD = AnalyticsPeriod(
    date_from=date(2026, 8, 1),
    date_to=date(2026, 8, 24),
    timezone="Asia/Kolkata",
)
_PASSWORD = "Analytics-Integration-Password-2026!"


def integration_settings() -> Settings:
    """Load ignored local PostgreSQL settings."""
    return Settings(
        _env_file=_REPOSITORY_ROOT / ".env",
        env=AppEnvironment.TEST,
        debug=False,
        docs_enabled=False,
        cors_allowed_origins=(),
    )


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[None]:
    """Ensure analytics tests use the current reviewed schema."""
    command.upgrade(Config(str(_ALEMBIC_CONFIG)), "head")
    yield


def test_live_aggregates_are_exact_currency_scoped_and_owner_isolated() -> None:
    """Exercise every 8.2 query against real PostgreSQL records."""
    asyncio.run(_exercise_live_aggregates())


def test_forecasting_source_is_cutoff_safe_complete_and_owner_isolated() -> None:
    """Exercise the Phase 9.2 source query and series builder in PostgreSQL."""
    asyncio.run(_exercise_forecasting_source())


def test_forecast_persistence_is_owner_scoped_immutable_and_cascading() -> None:
    """Exercise Phase 9.11 provenance, ownership, immutability, and erasure."""
    asyncio.run(_exercise_forecast_persistence())


def test_authenticated_analytics_api_returns_dashboard_ready_results() -> None:
    """Exercise both public analytics operations against real PostgreSQL."""
    settings = integration_settings()
    user_ids: list[UUID] = []

    try:
        with TestClient(
            create_app(settings),
            backend_options={
                "loop_factory": create_psycopg_compatible_event_loop,
            },
        ) as client:
            owner_id, token, account_id = _register_login_account(
                client,
                email=f"analytics-api-owner-{uuid4().hex}@falcon.example.com",
            )
            other_id, other_token, other_account_id = _register_login_account(
                client,
                email=f"analytics-api-other-{uuid4().hex}@falcon.example.com",
            )
            user_ids.extend((owner_id, other_id))
            _post_transaction(
                client,
                token=token,
                account_id=account_id,
                transaction_type=TransactionType.INCOME,
                amount="10000.0000",
                merchant="Employer",
            )
            _post_transaction(
                client,
                token=token,
                account_id=account_id,
                transaction_type=TransactionType.EXPENSE,
                amount="2500.0000",
                merchant="Swiggy",
            )
            _post_transaction(
                client,
                token=other_token,
                account_id=other_account_id,
                transaction_type=TransactionType.EXPENSE,
                amount="999999.0000",
                merchant="Must Not Leak",
                transaction_date="2026-08-03",
            )
            headers = {"Authorization": f"Bearer {token}"}
            params = {
                "date_from": "2026-08-01",
                "date_to": "2026-08-24",
                "comparison": "none",
            }

            cash_flow = client.get(
                "/api/v1/analytics/cash-flow",
                headers=headers,
                params={**params, "granularity": "day"},
            )
            assert cash_flow.status_code == 200, cash_flow.text
            cash_body = cash_flow.json()
            assert cash_body["metrics"]["gross_income"]["value"] == (
                "10000.0000"
            )
            assert cash_body["metrics"]["total_expense"]["value"] == (
                "2500.0000"
            )
            assert cash_body["metrics"]["net_cash_flow"]["value"] == (
                "7500.0000"
            )
            assert cash_body["previous_period"] is None
            assert len(cash_body["series"]) == 1

            spending = client.get(
                "/api/v1/analytics/spending",
                headers=headers,
                params={**params, "limit": "10"},
            )
            assert spending.status_code == 200, spending.text
            spending_body = spending.json()
            assert spending_body["total_expense"]["value"] == "2500.0000"
            assert spending_body["categories"] == []
            assert spending_body["merchants"] == [
                {
                    "normalized_merchant": "swiggy",
                    "display_name": "Swiggy",
                    "amount": {"value": "2500.0000"},
                    "share": {"value": "1.000000"},
                    "transaction_count": 1,
                }
            ]
            assert spending_body["accounts"][0]["account_id"] == str(
                account_id
            )
            assert spending_body["accounts"][0]["amount"]["value"] == (
                "2500.0000"
            )

            for observed in ("2026-06-01", "2026-07-01", "2026-08-01"):
                _post_transaction(
                    client,
                    token=token,
                    account_id=account_id,
                    transaction_type=TransactionType.EXPENSE,
                    amount="799.0000",
                    merchant="Netflix",
                    transaction_date=observed,
                )
            for observed in ("2026-06-03", "2026-07-03"):
                _post_transaction(
                    client,
                    token=other_token,
                    account_id=other_account_id,
                    transaction_type=TransactionType.EXPENSE,
                    amount="999999.0000",
                    merchant="Must Not Leak",
                    transaction_date=observed,
                )

            recurring = client.get(
                "/api/v1/analytics/recurring",
                headers=headers,
                params={
                    "date_from": "2026-05-01",
                    "date_to": "2026-08-24",
                    "minimum_occurrences": "3",
                },
            )
            assert recurring.status_code == 200, recurring.text
            recurring_body = recurring.json()
            assert recurring_body["summary"]["candidate_pattern_count"] == 1
            assert recurring_body["summary"]["detected_pattern_count"] == 1
            assert recurring_body["summary"][
                "detected_expense_observed"
            ]["value"] == "2397.0000"
            assert len(recurring_body["patterns"]) == 1
            assert recurring_body["patterns"][0]["normalized_merchant"] == (
                "netflix"
            )
            assert recurring_body["patterns"][0]["pattern_type"] == (
                "repeated_merchant"
            )
            assert recurring_body["patterns"][0]["decision"] == "detected"

            for _ in range(2):
                _post_transaction(
                    client,
                    token=token,
                    account_id=account_id,
                    transaction_type=TransactionType.EXPENSE,
                    amount="620.0000",
                    merchant="Food App",
                    transaction_date="2026-08-10",
                )
                _post_transaction(
                    client,
                    token=other_token,
                    account_id=other_account_id,
                    transaction_type=TransactionType.EXPENSE,
                    amount="888888.0000",
                    merchant="Must Not Leak",
                    transaction_date="2026-08-10",
                )

            spending_signals = client.get(
                "/api/v1/analytics/spending-signals",
                headers=headers,
                params={
                    "date_from": "2026-08-01",
                    "date_to": "2026-08-24",
                    "limit": "10",
                },
            )
            assert spending_signals.status_code == 200, spending_signals.text
            signal_body = spending_signals.json()
            assert signal_body["summary"]["evaluated_transaction_count"] == 4
            assert signal_body["summary"]["detected_signal_count"] == 1
            assert signal_body["summary"]["potential_leak_signal_count"] == 1
            assert signal_body["summary"]["anomaly_signal_count"] == 0
            assert len(signal_body["evaluations"]) == 8
            assert signal_body["signals"][0]["signal_type"] == (
                "duplicate_like_expense"
            )
            assert signal_body["signals"][0]["observed_amount"]["value"] == (
                "1240.0000"
            )
            assert signal_body["signals"][0]["normalized_merchant"] == "food app"
            assert "must not leak" not in str(signal_body).lower()

            (
                owner_budget_id,
                owner_category_id,
                other_budget_id,
                other_category_id,
            ) = asyncio.run(
                _create_budget_fixtures(
                    integration_settings(),
                    owner_id=owner_id,
                    other_id=other_id,
                )
            )
            _post_transaction(
                client,
                token=token,
                account_id=account_id,
                transaction_type=TransactionType.EXPENSE,
                amount="1000.0000",
                merchant="Budgeted Merchant",
                transaction_date="2026-08-12",
                category_id=owner_category_id,
            )
            _post_transaction(
                client,
                token=other_token,
                account_id=other_account_id,
                transaction_type=TransactionType.EXPENSE,
                amount="777777.0000",
                merchant="Other Budget Merchant",
                transaction_date="2026-08-12",
                category_id=other_category_id,
            )

            budget = client.get(
                f"/api/v1/analytics/budgets/{owner_budget_id}",
                headers=headers,
            )
            assert budget.status_code == 200, budget.text
            budget_body = budget.json()
            assert budget_body["budget"]["budget_id"] == str(owner_budget_id)
            assert budget_body["overall"]["spent_amount"]["value"] == (
                "5539.0000"
            )
            assert budget_body["configured_category_spend"]["value"] == (
                "1000.0000"
            )
            assert budget_body["outside_configured_categories"]["value"] == (
                "4539.0000"
            )
            assert len(budget_body["categories"]) == 1
            assert budget_body["categories"][0]["transaction_count"] == 1
            assert budget_body["categories"][0]["performance"]["spent_amount"][
                "value"
            ] == "1000.0000"
            assert "777777" not in str(budget_body)

            foreign_budget = client.get(
                f"/api/v1/analytics/budgets/{other_budget_id}",
                headers=headers,
            )
            assert foreign_budget.status_code == 404
            assert foreign_budget.json()["error"]["code"] == "budget_not_found"

            for index in range(4):
                _post_transaction(
                    client,
                    token=token,
                    account_id=account_id,
                    transaction_type=TransactionType.EXPENSE,
                    amount="100.0000",
                    merchant=f"Health Evidence {index}",
                    transaction_date=f"2026-08-{14 + index:02d}",
                    category_id=owner_category_id,
                )
                _post_transaction(
                    client,
                    token=other_token,
                    account_id=other_account_id,
                    transaction_type=TransactionType.EXPENSE,
                    amount="666666.0000",
                    merchant="Other Health Evidence",
                    transaction_date=f"2026-08-{14 + index:02d}",
                    category_id=other_category_id,
                )

            health_score = client.get(
                "/api/v1/analytics/health-score",
                headers=headers,
                params={
                    "date_from": "2026-08-01",
                    "date_to": "2026-08-24",
                    "budget_id": str(owner_budget_id),
                },
            )
            assert health_score.status_code == 200, health_score.text
            health_body = health_score.json()
            assert health_body["policy_version"] == "2026.1"
            assert health_body["status"] == "partial"
            assert health_body["score"] is not None
            assert len(health_body["factors"]) == 7
            budget_factor = next(
                factor
                for factor in health_body["factors"]
                if factor["factor"] == "budget_adherence"
            )
            assert budget_factor["status"] == "available"
            assert "666666" not in str(health_body)
            assert "other health evidence" not in str(health_body).lower()

            foreign_health_budget = client.get(
                "/api/v1/analytics/health-score",
                headers=headers,
                params={"budget_id": str(other_budget_id)},
            )
            assert foreign_health_budget.status_code == 404
            assert foreign_health_budget.json()["error"]["code"] == ("budget_not_found")

            insights = client.get(
                "/api/v1/analytics/insights",
                headers=headers,
                params={
                    "date_from": "2026-08-01",
                    "date_to": "2026-08-24",
                    "budget_id": str(owner_budget_id),
                    "limit": "10",
                },
            )
            assert insights.status_code == 200, insights.text
            insight_body = insights.json()
            assert insight_body["policy_version"] == "2026.1"
            assert insight_body["status"] == "available"
            assert insight_body["summary"]["active_insight_count"] >= 1
            assert insight_body["summary"]["returned_insight_count"] == len(
                insight_body["insights"]
            )
            assert all(
                item["lifecycle_state"] == "active"
                and len(item["insight_id"]) == 24
                for item in insight_body["insights"]
            )
            assert "666666" not in str(insight_body)
            assert "other health evidence" not in str(insight_body).lower()

            foreign_insight_budget = client.get(
                "/api/v1/analytics/insights",
                headers=headers,
                params={"budget_id": str(other_budget_id)},
            )
            assert foreign_insight_budget.status_code == 404
            assert foreign_insight_budget.json()["error"]["code"] == (
                "budget_not_found"
            )

            dashboard_params = {
                "date_from": "2026-08-01",
                "date_to": "2026-08-24",
                "granularity": "month",
                "limit": "50",
            }
            dashboard_before = client.get(
                "/api/v1/analytics/dashboard",
                headers=headers,
                params=dashboard_params,
            )
            assert dashboard_before.status_code == 200, dashboard_before.text
            before_body = dashboard_before.json()
            before_expense = Decimal(
                before_body["metrics"]["total_expense"]["value"]
            )
            assert before_body["metrics"]["total_expense"] == (
                before_body["spending"]["total_expense"]
            )

            corrected_transaction_id = _post_transaction(
                client,
                token=token,
                account_id=account_id,
                transaction_type=TransactionType.EXPENSE,
                amount="321.0000",
                merchant="Swiggy",
                transaction_date="2026-08-20",
            )
            dashboard_after_create = client.get(
                "/api/v1/analytics/dashboard",
                headers=headers,
                params=dashboard_params,
            )
            assert dashboard_after_create.status_code == 200
            after_create_body = dashboard_after_create.json()
            assert Decimal(
                after_create_body["metrics"]["total_expense"]["value"]
            ) == before_expense + Decimal("321.0000")
            assert after_create_body["context"]["freshness"][
                "source_last_updated_at"
            ] != before_body["context"]["freshness"]["source_last_updated_at"]

            classified = client.post(
                f"/api/v1/transactions/{corrected_transaction_id}/classification",
                headers=headers,
            )
            assert classified.status_code == 200, classified.text
            assert classified.json()["subcategory_code"] == "food_delivery"
            category_items = client.get(
                "/api/v1/categories",
                headers=headers,
            ).json()["items"]
            category_by_code = {
                item["classification_code"]: item
                for item in category_items
                if item["classification_code"] is not None
            }
            dashboard_after_classification = client.get(
                "/api/v1/analytics/dashboard",
                headers=headers,
                params=dashboard_params,
            ).json()
            food_delivery_before = next(
                item
                for item in dashboard_after_classification["spending"]["categories"]
                if item["classification_code"] == "food_delivery"
            )
            assert food_delivery_before["amount"]["value"] == "321.0000"

            corrected = client.post(
                (
                    f"/api/v1/transactions/{corrected_transaction_id}"
                    "/classification/correction"
                ),
                headers=headers,
                json={"category_id": category_by_code["restaurants"]["id"]},
            )
            assert corrected.status_code == 201, corrected.text
            dashboard_after_correction = client.get(
                "/api/v1/analytics/dashboard",
                headers=headers,
                params=dashboard_params,
            )
            assert dashboard_after_correction.status_code == 200
            correction_body = dashboard_after_correction.json()
            category_amounts = {
                item["classification_code"]: item["amount"]["value"]
                for item in correction_body["spending"]["categories"]
            }
            assert "food_delivery" not in category_amounts
            assert category_amounts["restaurants"] == "321.0000"
            assert correction_body["context"]["freshness"][
                "source_last_updated_at"
            ] != dashboard_after_classification["context"]["freshness"][
                "source_last_updated_at"
            ]
            assert "must not leak" not in str(correction_body).lower()
    finally:
        if user_ids:
            asyncio.run(_delete_users(integration_settings(), *user_ids))


def test_maximum_range_dashboard_meets_query_and_latency_budgets() -> None:
    """Prove the live-only core export stays bounded at the 366-day limit."""
    asyncio.run(_exercise_maximum_range_dashboard())


async def _exercise_live_aggregates() -> None:
    settings = integration_settings()
    resources = create_database_resources(settings)
    owner_id = uuid4()
    other_id = uuid4()
    owner = _user(owner_id, "analytics-owner")
    other = _user(other_id, "analytics-other")
    inr_account = _account(owner_id, "Historical INR", "INR")
    transfer_account = _account(owner_id, "Transfer INR", "INR")
    usd_account = _account(owner_id, "USD Account", "USD")
    other_account = _account(other_id, "Other INR", "INR")
    income_category = _category(owner_id, "Salary", CategoryKind.INCOME)
    expense_category = _category(owner_id, "Dining", CategoryKind.EXPENSE)
    transfer_group = TransferGroup(
        id=uuid4(),
        user_id=owner_id,
        created_at=_NOW,
        updated_at=_NOW,
    )

    try:
        async with transaction_scope(resources.session_factory) as session:
            session.add_all([owner, other])
        async with transaction_scope(resources.session_factory) as session:
            session.add_all(
                [inr_account, transfer_account, usd_account, other_account]
            )
            session.add_all([income_category, expense_category])
        async with transaction_scope(resources.session_factory) as session:
            session.add(transfer_group)
            session.add_all(
                [
                    _transaction(
                        owner_id,
                        inr_account.id,
                        amount="10000",
                        transaction_type=TransactionType.INCOME,
                        transaction_date=date(2026, 8, 1),
                        category_id=income_category.id,
                        merchant="Employer",
                    ),
                    _transaction(
                        owner_id,
                        inr_account.id,
                        amount="-2500",
                        transaction_type=TransactionType.EXPENSE,
                        transaction_date=date(2026, 8, 2),
                        category_id=expense_category.id,
                        merchant="SWIGGY",
                    ),
                    _transaction(
                        owner_id,
                        inr_account.id,
                        amount="-50",
                        transaction_type=TransactionType.EXPENSE,
                        transaction_date=date(2026, 8, 2),
                        category_id=None,
                        merchant="swiggy",
                    ),
                    _transaction(
                        owner_id,
                        inr_account.id,
                        amount="-100",
                        transaction_type=TransactionType.EXPENSE,
                        transaction_date=date(2026, 8, 2),
                        category_id=None,
                        merchant="Pending",
                        status=TransactionStatus.PENDING,
                    ),
                    _transaction(
                        owner_id,
                        inr_account.id,
                        amount="-500",
                        transaction_type=TransactionType.TRANSFER,
                        transaction_date=date(2026, 8, 3),
                        category_id=None,
                        merchant=None,
                        transfer_group_id=transfer_group.id,
                    ),
                    _transaction(
                        owner_id,
                        transfer_account.id,
                        amount="500",
                        transaction_type=TransactionType.TRANSFER,
                        transaction_date=date(2026, 8, 3),
                        category_id=None,
                        merchant=None,
                        transfer_group_id=transfer_group.id,
                    ),
                    _transaction(
                        owner_id,
                        inr_account.id,
                        amount="-10",
                        transaction_type=TransactionType.ADJUSTMENT,
                        transaction_date=date(2026, 8, 4),
                        category_id=None,
                        merchant=None,
                    ),
                    _transaction(
                        owner_id,
                        usd_account.id,
                        amount="-99",
                        transaction_type=TransactionType.EXPENSE,
                        transaction_date=date(2026, 8, 5),
                        category_id=None,
                        merchant="USD Merchant",
                    ),
                    _transaction(
                        other_id,
                        other_account.id,
                        amount="999999",
                        transaction_type=TransactionType.INCOME,
                        transaction_date=date(2026, 8, 1),
                        category_id=None,
                        merchant="Must Not Leak",
                    ),
                ]
            )
        async with transaction_scope(resources.session_factory) as session:
            persisted = await session.get(Account, inr_account.id)
            assert persisted is not None
            persisted.archived_at = _NOW

        repository = AnalyticsRepository()
        async with transaction_scope(resources.session_factory) as session:
            summary = await repository.get_summary(
                session,
                user_id=owner_id,
                period=_PERIOD,
                currency="INR",
            )
            daily = await repository.list_cash_flow_buckets(
                session,
                user_id=owner_id,
                period=_PERIOD,
                currency="INR",
                granularity=AnalyticsGranularity.DAY,
            )
            categories = await repository.list_category_aggregates(
                session,
                user_id=owner_id,
                period=_PERIOD,
                currency="INR",
            )
            merchants = await repository.list_merchant_aggregates(
                session,
                user_id=owner_id,
                period=_PERIOD,
                currency="INR",
            )
            accounts = await repository.list_account_aggregates(
                session,
                user_id=owner_id,
                period=_PERIOD,
                currency="INR",
            )

        assert summary.gross_income == Decimal("10000.0000")
        assert summary.total_expense == Decimal("2550.0000")
        assert summary.net_cash_flow == Decimal("7450.0000")
        assert summary.internal_transfer_volume == Decimal("500.0000")
        assert summary.net_adjustment == Decimal("-10.0000")
        assert summary.eligible_transaction_count == 3
        assert summary.categorized_transaction_count == 2
        assert summary.pending_count == 1
        assert summary.transfer_entry_count == 2
        assert summary.adjustment_count == 1
        assert summary.other_currency_count == 1
        assert summary.latest_transaction_date == date(2026, 8, 2)
        assert len(daily) == 2
        assert sum(row.gross_income for row in daily) == Decimal("10000.0000")
        assert sum(row.total_expense for row in daily) == Decimal("2550.0000")
        assert {row.name: row.amount for row in categories} == {
            "Salary": Decimal("10000.0000"),
            "Dining": Decimal("2500.0000"),
        }
        assert {row.normalized_merchant for row in merchants} == {
            "employer",
            "swiggy",
        }
        swiggy = next(
            row for row in merchants if row.normalized_merchant == "swiggy"
        )
        assert swiggy.total_expense == Decimal("2550.0000")
        assert swiggy.expense_transaction_count == 2
        assert swiggy.income_transaction_count == 0
        assert accounts[0].account_id == inr_account.id
        assert accounts[0].gross_income == Decimal("10000.0000")
        assert accounts[0].total_expense == Decimal("2550.0000")
        assert accounts[0].income_transaction_count == 1
        assert accounts[0].expense_transaction_count == 2
    finally:
        async with transaction_scope(resources.session_factory) as session:
            await session.execute(
                delete(User).where(User.id.in_((owner_id, other_id)))
            )
        await resources.dispose()


async def _exercise_forecasting_source() -> None:
    settings = integration_settings()
    resources = create_database_resources(settings)
    owner_id = uuid4()
    other_id = uuid4()
    owner = _user(owner_id, "forecasting-owner")
    other = _user(other_id, "forecasting-other")
    inr_account = _account(owner_id, "Forecast INR", "INR")
    usd_account = _account(owner_id, "Forecast USD", "USD")
    other_account = _account(other_id, "Other Forecast INR", "INR")
    cutoff = datetime(2026, 9, 7, 12, tzinfo=UTC)
    window = ForecastHistoryWindow(
        date_from=date(2026, 8, 1),
        date_to=date(2026, 8, 31),
        timezone="Asia/Kolkata",
        granularity=ForecastBucketGranularity.MONTH,
        data_cutoff_at=cutoff,
    )

    try:
        async with transaction_scope(resources.session_factory) as session:
            session.add_all([owner, other])
        async with transaction_scope(resources.session_factory) as session:
            session.add_all([inr_account, usd_account, other_account])
        eligible = [
            _transaction(
                owner_id,
                inr_account.id,
                amount="10000",
                transaction_type=TransactionType.INCOME,
                transaction_date=date(2026, 8, 1),
                category_id=None,
                merchant="Employer",
            ),
            _transaction(
                owner_id,
                inr_account.id,
                amount="-2500",
                transaction_type=TransactionType.EXPENSE,
                transaction_date=date(2026, 8, 2),
                category_id=None,
                merchant="Grocer",
            ),
        ]
        excluded_after_cutoff = _transaction(
            owner_id,
            inr_account.id,
            amount="777",
            transaction_type=TransactionType.INCOME,
            transaction_date=date(2026, 8, 3),
            category_id=None,
            merchant="Future Known",
        )
        excluded_after_cutoff.created_at = cutoff + timedelta(seconds=1)
        excluded_after_cutoff.updated_at = cutoff + timedelta(seconds=1)
        async with transaction_scope(resources.session_factory) as session:
            session.add_all(
                eligible
                + [
                    _transaction(
                        owner_id,
                        inr_account.id,
                        amount="-100",
                        transaction_type=TransactionType.EXPENSE,
                        transaction_date=date(2026, 8, 4),
                        category_id=None,
                        merchant="Pending",
                        status=TransactionStatus.PENDING,
                    ),
                    _transaction(
                        owner_id,
                        usd_account.id,
                        amount="-99",
                        transaction_type=TransactionType.EXPENSE,
                        transaction_date=date(2026, 8, 5),
                        category_id=None,
                        merchant="USD",
                    ),
                    _transaction(
                        other_id,
                        other_account.id,
                        amount="999999",
                        transaction_type=TransactionType.INCOME,
                        transaction_date=date(2026, 8, 1),
                        category_id=None,
                        merchant="Must Not Leak",
                    ),
                    excluded_after_cutoff,
                ]
            )
        async with transaction_scope(resources.session_factory) as session:
            persisted = await session.get(Account, inr_account.id)
            assert persisted is not None
            persisted.archived_at = cutoff

        async with transaction_scope(resources.session_factory) as session:
            buckets = await ForecastingRepository().list_source_buckets(
                session,
                user_id=owner_id,
                window=window,
                currency="INR",
            )
        series = build_forecast_series(
            target=ForecastTarget.NET_CASH_FLOW,
            currency="INR",
            window=window,
            buckets=buckets,
        )

        assert len(buckets) == 1
        assert buckets[0].gross_income == Decimal("10000.0000")
        assert buckets[0].total_expense == Decimal("2500.0000")
        assert buckets[0].transaction_count == 2
        assert series.points[0].value == Decimal("7500.0000")
        assert series.transaction_count == 2
    finally:
        async with transaction_scope(resources.session_factory) as session:
            await session.execute(
                delete(User).where(User.id.in_((owner_id, other_id)))
            )
        await resources.dispose()


async def _exercise_forecast_persistence() -> None:
    settings = integration_settings()
    resources = create_database_resources(settings)
    owner_id, other_id = uuid4(), uuid4()
    owner = _user(owner_id, "forecast-persistence-owner")
    other = _user(other_id, "forecast-persistence-other")
    repository = ForecastPersistenceRepository()

    payload = ForecastRunWrite(
        target=ForecastTarget.NET_CASH_FLOW,
        granularity=ForecastBucketGranularity.MONTH,
        currency="INR",
        history_start=date(2026, 1, 1),
        history_end=date(2026, 8, 31),
        data_cutoff_at=datetime(2026, 9, 1, tzinfo=UTC),
        source_last_updated_at=datetime(2026, 8, 31, tzinfo=UTC),
        forecast_start=date(2026, 9, 1),
        forecast_end=date(2026, 9, 1),
        contract_version="2026.1",
        quality_policy_version="2026.1",
        evaluation_policy_version="2026.1",
        feature_policy_version=None,
        selection_policy_version="2026.1",
        uncertainty_policy_version="2026.1",
        model_code="last_value",
        model_version="builtin-2026.1",
        model_parameters={},
        candidate_evidence={"evaluated": ["last_value"]},
        selection_metric="wape",
        validation_mae=Decimal("100.000000"),
        validation_rmse=Decimal("100.000000"),
        validation_wape=Decimal("0.100000"),
        validation_bias=Decimal("0.000000"),
        test_mae=Decimal("125.000000"),
        test_rmse=Decimal("125.000000"),
        test_wape=Decimal("0.125000"),
        test_bias=Decimal("25.000000"),
        uncertainty_method="absolute_residual_conformal",
        uncertainty_reliability="provisional",
        points=(
            ForecastPointWrite(
                step=1,
                period_start=date(2026, 9, 1),
                expected_value=Decimal("5000.0000"),
                lower_80=Decimal("4500.0000"),
                upper_80=Decimal("5500.0000"),
                lower_95=Decimal("4000.0000"),
                upper_95=Decimal("6000.0000"),
            ),
        ),
    )

    try:
        async with transaction_scope(resources.session_factory) as session:
            session.add_all([owner, other])
        async with transaction_scope(resources.session_factory) as session:
            created = await repository.create(
                session,
                user_id=owner_id,
                payload=payload,
            )
            run_id = created.id

        async with transaction_scope(resources.session_factory) as session:
            owned = await repository.get(
                session,
                user_id=owner_id,
                run_id=run_id,
            )
            denied = await repository.get(
                session,
                user_id=other_id,
                run_id=run_id,
            )
            other_history = await repository.list_recent(
                session,
                user_id=other_id,
                limit=10,
            )
            assert owned is not None
            assert len(owned.points) == 1
            assert owned.points[0].expected_value == Decimal("5000.0000")
            assert denied is None
            assert other_history == ()

        with pytest.raises(DBAPIError):
            async with transaction_scope(resources.session_factory) as session:
                await session.execute(
                    update(ForecastRun)
                    .where(ForecastRun.id == run_id)
                    .values(model_version="tampered")
                )

        async with transaction_scope(resources.session_factory) as session:
            await session.execute(delete(User).where(User.id == owner_id))
        async with transaction_scope(resources.session_factory) as session:
            assert await session.get(ForecastRun, run_id) is None
    finally:
        async with transaction_scope(resources.session_factory) as session:
            await session.execute(
                delete(User).where(User.id.in_((owner_id, other_id)))
            )
        await resources.dispose()


async def _exercise_maximum_range_dashboard() -> None:
    settings = integration_settings()
    resources = create_database_resources(settings)
    owner_id = uuid4()
    other_id = uuid4()
    owner = _user(owner_id, "analytics-performance-owner")
    other = _user(other_id, "analytics-performance-other")
    owner_account = _account(owner_id, "Performance INR", "INR")
    other_account = _account(other_id, "Other Performance INR", "INR")
    category = _category(owner_id, "Performance Dining", CategoryKind.EXPENSE)
    period_start = date(2025, 8, 24)
    observed_statements: list[str] = []

    def count_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            observed_statements.append(statement)

    try:
        async with transaction_scope(resources.session_factory) as session:
            session.add_all([owner, other])
        async with transaction_scope(resources.session_factory) as session:
            session.add_all([owner_account, other_account, category])
        async with transaction_scope(resources.session_factory) as session:
            session.add_all(
                [
                    _transaction(
                        owner_id,
                        owner_account.id,
                        amount="-10",
                        transaction_type=TransactionType.EXPENSE,
                        transaction_date=period_start + timedelta(days=index),
                        category_id=category.id,
                        merchant=f"Bounded Merchant {index % 50:02d}",
                    )
                    for index in range(366)
                ]
                + [
                    _transaction(
                        other_id,
                        other_account.id,
                        amount="-999999",
                        transaction_type=TransactionType.EXPENSE,
                        transaction_date=period_start + timedelta(days=index),
                        category_id=None,
                        merchant="Must Not Leak",
                    )
                    for index in range(50)
                ]
            )

        clock = Mock()
        clock.now.return_value = _NOW
        service = FinancialAnalyticsService(clock=clock)
        event.listen(
            resources.engine.sync_engine,
            "before_cursor_execute",
            count_statement,
        )
        try:
            async with transaction_scope(resources.session_factory) as session:
                started_at = perf_counter()
                response = await service.dashboard_export(
                    session,
                    user_id=owner_id,
                    trusted_timezone="Asia/Kolkata",
                    default_currency="INR",
                    selection=AnalyticsSelection(
                        date_from=period_start,
                        date_to=date(2026, 8, 24),
                        currency=None,
                        comparison=AnalyticsComparisonMode.NONE,
                    ),
                    granularity=AnalyticsGranularity.MONTH,
                    limit=50,
                )
                elapsed = perf_counter() - started_at
        finally:
            event.remove(
                resources.engine.sync_engine,
                "before_cursor_execute",
                count_statement,
            )

        assert response.context.period.day_count == 366
        assert response.metrics.total_expense.value == Decimal("3660.0000")
        assert response.context.completeness.eligible_transaction_count == 366
        assert len(response.series) == 13
        assert len(response.spending.merchants) == 50
        assert "must not leak" not in str(response).lower()
        assert len(observed_statements) == 5
        assert elapsed < ANALYTICS_DASHBOARD_PERFORMANCE_BUDGET_SECONDS
    finally:
        async with transaction_scope(resources.session_factory) as session:
            await session.execute(
                delete(User).where(User.id.in_((owner_id, other_id)))
            )
        await resources.dispose()


def _register_login_account(
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
            "name": f"Analytics {uuid4().hex[:8]}",
            "account_type": "bank",
            "opening_balance": "0.0000",
            "opening_balance_date": "2026-08-01",
        },
    )
    assert account.status_code == 201, account.text
    return user_id, token, UUID(account.json()["id"])


def _post_transaction(
    client: TestClient,
    *,
    token: str,
    account_id: UUID,
    transaction_type: TransactionType,
    amount: str,
    merchant: str,
    transaction_date: str = "2026-08-24",
    category_id: UUID | None = None,
) -> UUID:
    response = client.post(
        "/api/v1/transactions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "account_id": str(account_id),
            "category_id": str(category_id) if category_id is not None else None,
            "transaction_type": transaction_type.value,
            "amount": amount,
            "transaction_date": transaction_date,
            "description": f"Analytics API {transaction_type.value}",
            "merchant_name": merchant,
        },
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


async def _create_budget_fixtures(
    settings: Settings,
    *,
    owner_id: UUID,
    other_id: UUID,
) -> tuple[UUID, UUID, UUID, UUID]:
    resources = create_database_resources(settings)
    owner_category = _category(owner_id, "Budget Dining", CategoryKind.EXPENSE)
    other_category = _category(other_id, "Other Budget", CategoryKind.EXPENSE)
    owner_budget = _budget(owner_id, "Owner August", overall_limit="10000")
    other_budget = _budget(other_id, "Other August", overall_limit="900000")
    try:
        async with transaction_scope(resources.session_factory) as session:
            session.add_all([owner_category, other_category])
        async with transaction_scope(resources.session_factory) as session:
            session.add_all([owner_budget, other_budget])
        async with transaction_scope(resources.session_factory) as session:
            session.add_all(
                [
                    _budget_limit(
                        owner_id,
                        owner_budget.id,
                        owner_category.id,
                        "3000",
                    ),
                    _budget_limit(
                        other_id,
                        other_budget.id,
                        other_category.id,
                        "800000",
                    ),
                ]
            )
        return (
            owner_budget.id,
            owner_category.id,
            other_budget.id,
            other_category.id,
        )
    finally:
        await resources.dispose()


async def _delete_users(settings: Settings, *user_ids: UUID) -> None:
    resources = create_database_resources(settings)
    try:
        async with transaction_scope(resources.session_factory) as session:
            await session.execute(delete(User).where(User.id.in_(user_ids)))
    finally:
        await resources.dispose()


def _user(user_id: UUID, label: str) -> User:
    return User(
        id=user_id,
        email=f"{label}-{uuid4().hex}@falcon.test",
        status=UserStatus.ACTIVE,
        display_name=label,
        timezone="Asia/Kolkata",
        default_currency="INR",
        email_verified_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _account(user_id: UUID, name: str, currency: str) -> Account:
    return Account(
        id=uuid4(),
        user_id=user_id,
        name=name,
        account_type=AccountType.BANK,
        institution_name=None,
        masked_reference=None,
        currency=currency,
        opening_balance=Decimal("0"),
        opening_balance_date=date(2026, 1, 1),
        archived_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _category(user_id: UUID, name: str, kind: CategoryKind) -> Category:
    return Category(
        id=uuid4(),
        user_id=user_id,
        name=name,
        normalized_name=f"analytics_{name.lower()}",
        classification_code=None,
        kind=kind,
        parent_id=None,
        is_system=False,
        display_order=0,
        archived_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _budget(user_id: UUID, name: str, *, overall_limit: str) -> Budget:
    return Budget(
        id=uuid4(),
        user_id=user_id,
        name=f"{name} {uuid4().hex[:8]}",
        period_start_date=date(2026, 8, 1),
        period_end_date=date(2026, 8, 31),
        currency="INR",
        overall_limit=Decimal(overall_limit),
        archived_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _budget_limit(
    user_id: UUID,
    budget_id: UUID,
    category_id: UUID,
    amount: str,
) -> BudgetLimit:
    return BudgetLimit(
        id=uuid4(),
        user_id=user_id,
        budget_id=budget_id,
        category_id=category_id,
        limit_amount=Decimal(amount),
        created_at=_NOW,
        updated_at=_NOW,
    )


def _transaction(
    user_id: UUID,
    account_id: UUID,
    *,
    amount: str,
    transaction_type: TransactionType,
    transaction_date: date,
    category_id: UUID | None,
    merchant: str | None,
    status: TransactionStatus = TransactionStatus.POSTED,
    transfer_group_id: UUID | None = None,
) -> Transaction:
    source_type = TransactionSourceType.MANUAL
    if transaction_type is TransactionType.TRANSFER:
        source_type = TransactionSourceType.TRANSFER
    elif transaction_type is TransactionType.ADJUSTMENT:
        source_type = TransactionSourceType.ADJUSTMENT
    return Transaction(
        id=uuid4(),
        user_id=user_id,
        account_id=account_id,
        category_id=category_id,
        import_job_id=None,
        transfer_group_id=transfer_group_id,
        transaction_type=transaction_type,
        amount=Decimal(amount),
        transaction_date=transaction_date,
        description=f"Analytics {transaction_type.value}",
        merchant_name=merchant,
        source_type=source_type,
        external_source_hash=None,
        status=status,
        is_user_modified=False,
        created_at=_NOW,
        updated_at=_NOW,
    )
