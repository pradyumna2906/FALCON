"""Immutable owner-scoped goal-planning snapshot tests."""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.goal_planning import (
    GoalPlanningSnapshotService,
    PlanningEvidenceRepository,
    PlanningSnapshotWarning,
)
from falcon_api.goal_planning.snapshot import (
    PlanningBudgetEvidence,
    PlanningEvidenceRows,
    PlanningFinancialEvidence,
    PlanningProfileEvidence,
)
from falcon_api.models.enums import (
    GoalPriority,
    GoalStatus,
    GoalType,
    ProfileCompletionStatus,
)
from falcon_api.models.planning import Goal


_NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return _NOW


def _goal() -> Goal:
    return Goal(
        id=uuid4(),
        user_id=uuid4(),
        name="Education Fund",
        goal_type=GoalType.EDUCATION,
        target_amount=Decimal("10000"),
        starting_amount=Decimal("1000"),
        currency="INR",
        target_date=date(2027, 3, 14),
        priority=GoalPriority.HIGH,
        status=GoalStatus.ACTIVE,
        description=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _forecast(*, reliability: str = "normal", future: bool = True):
    period = date(2026, 10, 1) if future else date(2026, 8, 1)
    return SimpleNamespace(
        id=uuid4(),
        target="savings_amount",
        granularity="month",
        currency="INR",
        uncertainty_reliability=reliability,
        created_at=_NOW,
        points=[
            SimpleNamespace(
                period_start=period,
                lower_95=Decimal("500"),
                expected_value=Decimal("1000"),
                upper_95=Decimal("1500"),
            )
        ],
    )


def _evidence(
    *,
    forecast=None,
    profile=True,
    budget_count: int = 1,
    excluded: int = 0,
    liability_count: int = 1,
    payment_count: int = 1,
) -> PlanningEvidenceRows:
    goal = _goal()
    return PlanningEvidenceRows(
        goals=(goal,),
        contribution_totals=((goal.id, Decimal("2000")),),
        contribution_count=1,
        excluded_currency_goal_count=excluded,
        profile=(
            PlanningProfileEvidence(
                completion_status=ProfileCompletionStatus.COMPLETE,
                income_stability="stable",
                emergency_fund_target_months=Decimal("6"),
                updated_at=_NOW,
            )
            if profile
            else None
        ),
        finances=PlanningFinancialEvidence(
            liquid_balance=Decimal("50000"),
            liability_account_count=liability_count,
            liability_payment_count=payment_count,
            outstanding_debt=Decimal("100000"),
            monthly_debt_payment=Decimal("5000"),
            source_last_updated_at=_NOW,
        ),
        budgets=PlanningBudgetEvidence(
            active_budget_count=budget_count,
            budget_with_overall_limit_count=budget_count,
            total_overall_limit=Decimal("30000"),
            source_last_updated_at=_NOW if budget_count else None,
        ),
        forecast=forecast,
    )


def test_snapshot_freezes_progress_capacity_provenance_and_hash() -> None:
    repository = AsyncMock(spec=PlanningEvidenceRepository)
    forecast = _forecast()
    repository.load.return_value = _evidence(forecast=forecast)
    service = GoalPlanningSnapshotService(
        repository=repository,
        clock=FixedClock(),
    )
    user_id = uuid4()

    first = asyncio.run(
        service.build(
            AsyncMock(),
            user_id=user_id,
            currency=" inr ",
            trusted_timezone="Asia/Kolkata",
        )
    )
    second = asyncio.run(
        service.build(
            AsyncMock(),
            user_id=user_id,
            currency="INR",
            trusted_timezone="Asia/Kolkata",
        )
    )

    assert first.snapshot_id == second.snapshot_id
    assert len(first.snapshot_id) == 64
    assert first.currency == "INR"
    assert first.local_date == date(2026, 9, 14)
    assert first.goals[0].current_amount == Decimal("3000.0000")
    assert first.savings_capacity is not None
    assert first.savings_capacity.protected_total == Decimal("500.0000")
    assert first.provenance.forecast_run_id == forecast.id
    assert first.warnings == ()
    call = repository.load.await_args_list[0]
    assert call.kwargs["user_id"] == user_id
    assert call.kwargs["cutoff_at"] == _NOW


def test_snapshot_reports_missing_and_excluded_evidence() -> None:
    repository = AsyncMock(spec=PlanningEvidenceRepository)
    evidence = _evidence(
        profile=False,
        budget_count=0,
        excluded=2,
        liability_count=2,
        payment_count=1,
    )
    evidence = PlanningEvidenceRows(
        goals=(),
        contribution_totals=(),
        contribution_count=0,
        excluded_currency_goal_count=evidence.excluded_currency_goal_count,
        profile=evidence.profile,
        finances=evidence.finances,
        budgets=evidence.budgets,
        forecast=None,
    )
    repository.load.return_value = evidence

    result = asyncio.run(
        GoalPlanningSnapshotService(
            repository=repository,
            clock=FixedClock(),
        ).build(
            AsyncMock(),
            user_id=uuid4(),
            currency="INR",
            trusted_timezone="UTC",
        )
    )

    assert set(result.warnings) == {
        PlanningSnapshotWarning.NO_ACTIVE_GOALS,
        PlanningSnapshotWarning.MIXED_CURRENCY_GOALS_EXCLUDED,
        PlanningSnapshotWarning.PROFILE_MISSING,
        PlanningSnapshotWarning.BUDGET_MISSING,
        PlanningSnapshotWarning.DEBT_PAYMENT_INCOMPLETE,
        PlanningSnapshotWarning.SAVINGS_FORECAST_MISSING,
    }


def test_snapshot_warns_for_incomplete_profile_and_forecast_quality() -> None:
    repository = AsyncMock(spec=PlanningEvidenceRepository)
    evidence = _evidence(forecast=_forecast(reliability="provisional"))
    repository.load.return_value = PlanningEvidenceRows(
        goals=evidence.goals,
        contribution_totals=evidence.contribution_totals,
        contribution_count=evidence.contribution_count,
        excluded_currency_goal_count=0,
        profile=PlanningProfileEvidence(
            completion_status=ProfileCompletionStatus.DRAFT,
            income_stability=None,
            emergency_fund_target_months=None,
            updated_at=_NOW,
        ),
        finances=evidence.finances,
        budgets=evidence.budgets,
        forecast=evidence.forecast,
    )

    result = asyncio.run(
        GoalPlanningSnapshotService(
            repository=repository,
            clock=FixedClock(),
        ).build(
            AsyncMock(),
            user_id=uuid4(),
            currency="INR",
            trusted_timezone="UTC",
        )
    )

    assert PlanningSnapshotWarning.PROFILE_INCOMPLETE in result.warnings
    assert PlanningSnapshotWarning.SAVINGS_FORECAST_PROVISIONAL in result.warnings


def test_snapshot_marks_forecast_without_future_points_unusable() -> None:
    repository = AsyncMock(spec=PlanningEvidenceRepository)
    repository.load.return_value = _evidence(forecast=_forecast(future=False))

    result = asyncio.run(
        GoalPlanningSnapshotService(
            repository=repository,
            clock=FixedClock(),
        ).build(
            AsyncMock(),
            user_id=uuid4(),
            currency="INR",
            trusted_timezone="UTC",
        )
    )

    assert result.savings_capacity is None
    assert PlanningSnapshotWarning.SAVINGS_FORECAST_UNUSABLE in result.warnings


def _compiled(statement) -> tuple[str, dict[str, object]]:
    compiled = statement.compile(dialect=postgresql.dialect())
    return str(compiled), compiled.params


def test_repository_goal_and_forecast_queries_are_scoped() -> None:
    repository = PlanningEvidenceRepository()
    session = AsyncMock(spec=AsyncSession)
    scalar_rows = Mock()
    scalar_rows.all.return_value = []
    session.scalars.return_value = scalar_rows
    session.scalar.side_effect = [2, None]
    user_id = uuid4()

    asyncio.run(
        repository._goals(
            session,
            user_id=user_id,
            currency="INR",
            cutoff_at=_NOW,
        )
    )
    goal_sql, goal_params = _compiled(session.scalars.await_args.args[0])
    assert "goals.user_id =" in goal_sql
    assert "goals.currency =" in goal_sql
    assert "goals.created_at <=" in goal_sql
    assert user_id in goal_params.values()

    assert asyncio.run(
        repository._excluded_goal_count(
            session,
            user_id=user_id,
            currency="INR",
            cutoff_at=_NOW,
        )
    ) == 2
    assert asyncio.run(
        repository._forecast(
            session,
            user_id=user_id,
            currency="INR",
            cutoff_at=_NOW,
        )
    ) is None
    forecast_sql, forecast_params = _compiled(session.scalar.await_args.args[0])
    assert "forecast_runs.user_id =" in forecast_sql
    assert "forecast_runs.data_cutoff_at <=" in forecast_sql
    assert "savings_amount" in forecast_params.values()
    assert "month" in forecast_params.values()


def test_repository_contribution_profile_budget_and_finance_evidence() -> None:
    repository = PlanningEvidenceRepository()
    user_id = uuid4()
    goal_id = uuid4()

    contribution_session = AsyncMock(spec=AsyncSession)
    contribution_result = Mock()
    contribution_result.mappings.return_value.all.return_value = [
        {"goal_id": goal_id, "amount": Decimal("2500"), "count": 2}
    ]
    contribution_session.execute.return_value = contribution_result
    totals, count = asyncio.run(
        repository._contributions(
            contribution_session,
            user_id=user_id,
            goal_ids=(goal_id,),
            cutoff_at=_NOW,
        )
    )
    contribution_sql, _ = _compiled(
        contribution_session.execute.await_args.args[0]
    )
    assert totals == ((goal_id, Decimal("2500.0000")),)
    assert count == 2
    assert "goal_contributions.user_id =" in contribution_sql
    assert asyncio.run(
        repository._contributions(
            contribution_session,
            user_id=user_id,
            goal_ids=(),
            cutoff_at=_NOW,
        )
    ) == ((), 0)

    profile_session = AsyncMock(spec=AsyncSession)
    profile_session.scalar.side_effect = [
        SimpleNamespace(
            completion_status=ProfileCompletionStatus.COMPLETE,
            income_stability="stable",
            emergency_fund_target_months=Decimal("6"),
            updated_at=_NOW,
        ),
        None,
    ]
    profile = asyncio.run(
        repository._profile(
            profile_session,
            user_id=user_id,
            cutoff_at=_NOW,
        )
    )
    assert profile is not None and profile.income_stability == "stable"
    assert asyncio.run(
        repository._profile(
            profile_session,
            user_id=user_id,
            cutoff_at=_NOW,
        )
    ) is None

    budget_session = AsyncMock(spec=AsyncSession)
    budget_result = Mock()
    budget_result.mappings.return_value.one.return_value = {
        "budget_count": 1,
        "limit_count": 1,
        "limit": Decimal("30000"),
        "updated_at": _NOW,
    }
    budget_session.execute.return_value = budget_result
    budgets = asyncio.run(
        repository._budgets(
            budget_session,
            user_id=user_id,
            currency="INR",
            cutoff_at=_NOW,
            local_date=date(2026, 9, 14),
        )
    )
    budget_sql, _ = _compiled(budget_session.execute.await_args.args[0])
    assert budgets.total_overall_limit == Decimal("30000.0000")
    assert "budgets.user_id =" in budget_sql
    assert "budgets.currency =" in budget_sql

    finance_session = AsyncMock(spec=AsyncSession)
    finance_session.scalar.side_effect = [Decimal("50000"), _NOW, _NOW]
    finance_result = Mock()
    finance_result.mappings.return_value.one.return_value = {
        "account_count": 2,
        "payment_count": 1,
        "outstanding": Decimal("100000"),
        "monthly_payment": Decimal("5000"),
        "account_updated": _NOW,
        "liability_updated": _NOW,
    }
    finance_session.execute.return_value = finance_result
    finances = asyncio.run(
        repository._finances(
            finance_session,
            user_id=user_id,
            currency="INR",
            cutoff_at=_NOW,
            local_date=date(2026, 9, 14),
        )
    )
    liability_sql, liability_params = _compiled(
        finance_session.execute.await_args.args[0]
    )
    assert finances.liquid_balance == Decimal("50000.0000")
    assert finances.outstanding_debt == Decimal("100000.0000")
    assert finances.source_last_updated_at == _NOW
    assert "accounts.user_id =" in liability_sql
    assert user_id in liability_params.values()
