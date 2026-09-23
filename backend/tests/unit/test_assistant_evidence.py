"""Owner-scoped evidence registry and adapter tests."""

import asyncio
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.analytics.application import FinancialAnalyticsService
from falcon_api.analytics.semantics import AnalyticsConfidenceLevel
from falcon_api.assistant import (
    AnalyticsEvidenceAdapter,
    AssistantEvidenceQuery,
    AssistantEvidenceRecord,
    AssistantEvidenceRegistry,
    AssistantEvidenceSource,
    AssistantIntent,
    AssistantKnowledgeTopic,
    AssistantReliability,
    ForecastEvidenceAdapter,
    GoalPlanEvidenceAdapter,
    GoalProgressEvidenceAdapter,
    ScenarioEvidenceAdapter,
)
from falcon_api.forecasting.persistence import ForecastPersistenceRepository
from falcon_api.goal_planning.contributions import ContributionService
from falcon_api.goal_planning.persistence import GoalPlanRepository
from falcon_api.models.enums import GoalPlanStatus
from falcon_api.scenario_simulation.persistence import ScenarioSimulationRepository


NOW = datetime(2026, 9, 22, 10, tzinfo=UTC)
OWNER_ID = uuid4()
RESOURCE_ID = uuid4()


class FixedClock:
    def now(self):
        return NOW


def _record(source=AssistantEvidenceSource.KNOWLEDGE, *, reference="record"):
    return AssistantEvidenceRecord(
        source=source,
        reference=reference,
        label="Reviewed evidence",
        cutoff_at=NOW,
        policy_version="2026.1",
        reliability=AssistantReliability.NORMAL,
        payload={},
    )


class FakeAdapter:
    def __init__(self, source, records=()):
        self.source = source
        self.records = records
        self.calls = []

    async def retrieve(self, session, *, user_id, intent, query):
        self.calls.append((session, user_id, intent, query))
        return self.records


def test_evidence_query_enforces_source_specific_server_shape() -> None:
    analytics = AssistantEvidenceQuery(
        source=AssistantEvidenceSource.ANALYTICS,
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
        trusted_timezone="Asia/Kolkata",
        currency="inr",
    )
    knowledge = AssistantEvidenceQuery(
        source=AssistantEvidenceSource.KNOWLEDGE,
        text=" emergency fund ",
        topics=(AssistantKnowledgeTopic.EMERGENCY_FUNDS,),
    )

    assert analytics.currency == "INR"
    assert knowledge.text == "emergency fund"
    with pytest.raises(ValueError, match="requires text"):
        AssistantEvidenceQuery(source=AssistantEvidenceSource.KNOWLEDGE)
    with pytest.raises(ValueError, match="server-selected ID"):
        AssistantEvidenceQuery(source=AssistantEvidenceSource.FORECAST)
    with pytest.raises(ValueError, match="trusted timezone"):
        AssistantEvidenceQuery(
            source=AssistantEvidenceSource.GOAL_PROGRESS,
            reference_id=RESOURCE_ID,
        )
    with pytest.raises(ValueError, match="immutable ID"):
        AssistantEvidenceQuery(
            source=AssistantEvidenceSource.GOAL_PLAN,
            reference_id=RESOURCE_ID,
            currency="INR",
        )


def test_evidence_record_is_prompt_safe_canonical_and_deeply_immutable() -> None:
    record = AssistantEvidenceRecord(
        source=AssistantEvidenceSource.FORECAST,
        reference=str(RESOURCE_ID),
        label="Savings forecast",
        cutoff_at=NOW,
        policy_version="2026.1",
        reliability=AssistantReliability.PROVISIONAL,
        payload={"run_id": RESOURCE_ID, "points": ({"value": Decimal("1.0000")},)},
    )
    replay = AssistantEvidenceRecord(
        source=AssistantEvidenceSource.FORECAST,
        reference=str(RESOURCE_ID),
        label="Savings forecast",
        cutoff_at=NOW,
        policy_version="2026.1",
        reliability=AssistantReliability.PROVISIONAL,
        payload={"points": ({"value": Decimal("1.0000")},), "run_id": RESOURCE_ID},
    )

    assert record.evidence_id == replay.evidence_id
    with pytest.raises(TypeError):
        record.payload["run_id"] = uuid4()  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        record.label = "changed"  # type: ignore[misc]
    with pytest.raises(ValueError, match="Unavailable"):
        AssistantEvidenceRecord(
            source=AssistantEvidenceSource.KNOWLEDGE,
            reference="x",
            label="x",
            cutoff_at=NOW,
            policy_version="2026.1",
            reliability=AssistantReliability.UNAVAILABLE,
            payload={},
        )


def test_registry_authorizes_before_dispatch_and_preserves_owner() -> None:
    query = AssistantEvidenceQuery(
        source=AssistantEvidenceSource.FORECAST,
        reference_id=RESOURCE_ID,
    )
    adapter = FakeAdapter(
        AssistantEvidenceSource.FORECAST,
        (_record(AssistantEvidenceSource.FORECAST),),
    )
    registry = AssistantEvidenceRegistry((adapter,))
    session = AsyncMock(spec=AsyncSession)

    result = asyncio.run(
        registry.retrieve(
            session,
            user_id=OWNER_ID,
            intent=AssistantIntent.EXPLAIN_FORECAST,
            queries=(query,),
        )
    )

    assert len(result) == 1
    assert adapter.calls[0][1] == OWNER_ID
    with pytest.raises(PermissionError, match="ownership"):
        asyncio.run(
            registry.retrieve(
                session,
                user_id=None,
                intent=AssistantIntent.EXPLAIN_FORECAST,
                queries=(query,),
            )
        )
    assert len(adapter.calls) == 1


def test_registry_rejects_duplicate_missing_wrong_or_excess_evidence() -> None:
    query = AssistantEvidenceQuery(
        source=AssistantEvidenceSource.KNOWLEDGE,
        text="budgeting basics",
    )
    session = AsyncMock(spec=AsyncSession)
    with pytest.raises(ValueError, match="sources must be unique"):
        asyncio.run(
            AssistantEvidenceRegistry((FakeAdapter(AssistantEvidenceSource.KNOWLEDGE),)).retrieve(
                session,
                user_id=None,
                intent=AssistantIntent.FINANCIAL_EDUCATION,
                queries=(query, query),
            )
        )
    with pytest.raises(ValueError, match="No adapter"):
        asyncio.run(
            AssistantEvidenceRegistry(()).retrieve(
                session,
                user_id=None,
                intent=AssistantIntent.FINANCIAL_EDUCATION,
                queries=(query,),
            )
        )
    wrong = FakeAdapter(
        AssistantEvidenceSource.KNOWLEDGE,
        (_record(AssistantEvidenceSource.FORECAST),),
    )
    with pytest.raises(ValueError, match="wrong source"):
        asyncio.run(
            AssistantEvidenceRegistry((wrong,)).retrieve(
                session,
                user_id=None,
                intent=AssistantIntent.FINANCIAL_EDUCATION,
                queries=(query,),
            )
        )
    excess = FakeAdapter(
        AssistantEvidenceSource.KNOWLEDGE,
        tuple(_record(reference=f"record-{index}") for index in range(21)),
    )
    with pytest.raises(ValueError, match="record limit"):
        asyncio.run(
            AssistantEvidenceRegistry((excess,)).retrieve(
                session,
                user_id=None,
                intent=AssistantIntent.FINANCIAL_EDUCATION,
                queries=(query,),
            )
        )


def test_analytics_adapter_removes_account_evidence_and_forwards_owner_scope() -> None:
    service = AsyncMock(spec=FinancialAnalyticsService)
    context = SimpleNamespace(
        period=SimpleNamespace(date_from=date(2026, 9, 1), date_to=date(2026, 9, 30)),
        currency="INR",
        freshness=SimpleNamespace(calculated_at=NOW),
        completeness=SimpleNamespace(data_confidence=AnalyticsConfidenceLevel.HIGH),
        contract_version="2026.1",
    )
    metrics = SimpleNamespace(
        gross_income=SimpleNamespace(value=Decimal("1000")),
        total_expense=SimpleNamespace(value=Decimal("600")),
        net_cash_flow=SimpleNamespace(value=Decimal("400")),
        savings_amount=SimpleNamespace(value=Decimal("400")),
        savings_rate=SimpleNamespace(value=Decimal("0.4")),
    )
    service.dashboard_export.return_value = SimpleNamespace(
        context=context,
        metrics=metrics,
        spending=SimpleNamespace(
            categories=(SimpleNamespace(name="Food", amount=SimpleNamespace(value=Decimal("100")), share=SimpleNamespace(value=Decimal("0.166667")), transaction_count=2),),
            merchants=(),
            accounts=(SimpleNamespace(account_id=uuid4(), name="Private bank"),),
        ),
        model_dump=lambda mode: {"summary": "bounded"},
    )
    adapter = AnalyticsEvidenceAdapter(service)
    query = AssistantEvidenceQuery(
        source=AssistantEvidenceSource.ANALYTICS,
        trusted_timezone="Asia/Kolkata",
        currency="INR",
        limit=5,
    )

    records = asyncio.run(adapter.retrieve(AsyncMock(spec=AsyncSession), user_id=OWNER_ID, intent=AssistantIntent.EXPLAIN_DASHBOARD, query=query))

    assert len(records) == 1
    assert "accounts" not in records[0].payload["spending_summary"]
    assert "account_id" not in repr(records[0].payload)
    assert service.dashboard_export.await_args.kwargs["user_id"] == OWNER_ID


def test_forecast_adapter_uses_validation_quality_not_final_test_metrics() -> None:
    repository = AsyncMock(spec=ForecastPersistenceRepository)
    repository.get.return_value = SimpleNamespace(
        id=RESOURCE_ID,
        target="savings_amount",
        currency="INR",
        data_cutoff_at=NOW,
        forecast_start=date(2026, 10, 1),
        forecast_end=date(2026, 11, 1),
        model_code="seasonal_naive",
        model_version="2026.1",
        selection_metric="wape",
        validation_mae=Decimal("20"),
        validation_rmse=Decimal("25"),
        validation_wape=Decimal("0.1"),
        test_mae=Decimal("999"),
        uncertainty_reliability="provisional",
        contract_version="2026.1",
        quality_policy_version="2026.1",
        evaluation_policy_version="2026.1",
        selection_policy_version="2026.1",
        uncertainty_policy_version="2026.1",
        points=(SimpleNamespace(period_start=date(2026, 10, 1), expected_value=Decimal("500"), lower_80=Decimal("450"), upper_80=Decimal("550"), lower_95=Decimal("400"), upper_95=Decimal("600")),),
    )
    adapter = ForecastEvidenceAdapter(repository)
    query = AssistantEvidenceQuery(source=AssistantEvidenceSource.FORECAST, reference_id=RESOURCE_ID)

    records = asyncio.run(adapter.retrieve(AsyncMock(spec=AsyncSession), user_id=OWNER_ID, intent=AssistantIntent.EXPLAIN_FORECAST, query=query))

    assert records[0].reliability is AssistantReliability.PROVISIONAL
    assert "test_mae" not in records[0].payload["quality"]
    repository.get.assert_awaited_once_with(
        ANY,
        user_id=OWNER_ID,
        run_id=RESOURCE_ID,
    )


def test_goal_progress_adapter_calls_existing_exact_service() -> None:
    service = AsyncMock(spec=ContributionService)
    service.progress.return_value = SimpleNamespace(
        goal_id=RESOURCE_ID,
        goal_name="Tuition",
        currency="INR",
        target_amount=Decimal("100000"),
        current_amount=Decimal("25000"),
        remaining_amount=Decimal("75000"),
        funding_percentage=Decimal("25"),
        target_date=date(2027, 6, 1),
        required_monthly_contribution=Decimal("7500"),
        funding_state=SimpleNamespace(value="in_progress"),
    )
    adapter = GoalProgressEvidenceAdapter(service=service, clock=FixedClock())
    query = AssistantEvidenceQuery(
        source=AssistantEvidenceSource.GOAL_PROGRESS,
        reference_id=RESOURCE_ID,
        trusted_timezone="Asia/Kolkata",
    )

    result = asyncio.run(adapter.retrieve(AsyncMock(spec=AsyncSession), user_id=OWNER_ID, intent=AssistantIntent.EXPLAIN_GOAL_PROGRESS, query=query))

    assert result[0].payload["remaining_amount"] == Decimal("75000")
    service.progress.assert_awaited_once_with(
        ANY,
        user_id=OWNER_ID,
        goal_id=RESOURCE_ID,
        trusted_timezone="Asia/Kolkata",
    )


def test_goal_plan_and_scenario_adapters_hide_foreign_or_missing_records() -> None:
    plan_repository = AsyncMock(spec=GoalPlanRepository)
    scenario_repository = AsyncMock(spec=ScenarioSimulationRepository)
    plan_repository.get.return_value = None
    scenario_repository.get.return_value = None
    session = AsyncMock(spec=AsyncSession)

    plan = asyncio.run(GoalPlanEvidenceAdapter(plan_repository).retrieve(session, user_id=OWNER_ID, intent=AssistantIntent.EXPLAIN_GOAL_PLAN, query=AssistantEvidenceQuery(source=AssistantEvidenceSource.GOAL_PLAN, reference_id=RESOURCE_ID)))
    scenario = asyncio.run(ScenarioEvidenceAdapter(scenario_repository).retrieve(session, user_id=OWNER_ID, intent=AssistantIntent.COMPARE_SCENARIOS, query=AssistantEvidenceQuery(source=AssistantEvidenceSource.SCENARIO_SIMULATION, reference_id=RESOURCE_ID)))

    assert plan == ()
    assert scenario == ()
    plan_repository.get.assert_awaited_once_with(session, user_id=OWNER_ID, plan_id=RESOURCE_ID)
    scenario_repository.get.assert_awaited_once_with(session, user_id=OWNER_ID, run_id=RESOURCE_ID)


def test_goal_plan_adapter_serializes_bounded_schedule_without_owner_keys() -> None:
    repository = AsyncMock(spec=GoalPlanRepository)
    allocation = SimpleNamespace(
        rank=1,
        amount=Decimal("100"),
        cumulative_amount=Decimal("100"),
        projected_remaining_amount=Decimal("900"),
    )
    period = SimpleNamespace(
        period_start=date(2026, 10, 1),
        available_capacity=Decimal("150"),
        allocated_amount=Decimal("100"),
        unallocated_amount=Decimal("50"),
        allocations=(allocation,),
    )
    outcome = SimpleNamespace(
        goal_name="Education",
        goal_type="education",
        priority="high",
        target_date=date(2027, 6, 1),
        target_amount=Decimal("1000"),
        current_amount=Decimal("0"),
        rank=1,
        allocated_amount=Decimal("100"),
        projected_remaining_amount=Decimal("900"),
        completion_probability=Decimal("0.8"),
        deadline_met=True,
        evidence_reliability="normal",
        protected_shortfall=Decimal("100"),
        expected_shortfall=Decimal("0"),
    )
    repository.get.return_value = SimpleNamespace(
        id=RESOURCE_ID,
        planning_cutoff_at=NOW,
        currency="INR",
        status=GoalPlanStatus.GENERATED,
        forecast_reliability="normal",
        outcomes=(outcome,),
        periods=(period,),
        emergency_reserve_amount=Decimal("200"),
        guardrail_reason_codes=["reserve_protected"],
        reason_codes=["optimized_plan_selected"],
        contract_version="2026.1",
        plan_policy_version="2026.1",
        feasibility_policy_version="2026.1",
        ranking_policy_version="2026.1",
        optimization_policy_version="2026.1",
        guardrail_policy_version="2026.1",
    )

    records = asyncio.run(
        GoalPlanEvidenceAdapter(repository).retrieve(
            AsyncMock(spec=AsyncSession),
            user_id=OWNER_ID,
            intent=AssistantIntent.EXPLAIN_GOAL_PLAN,
            query=AssistantEvidenceQuery(
                source=AssistantEvidenceSource.GOAL_PLAN,
                reference_id=RESOURCE_ID,
            ),
        )
    )

    assert records[0].payload["goals"][0]["name"] == "Education"
    assert records[0].payload["periods"][0]["allocated_amount"] == Decimal("100")
    assert "user_id" not in repr(records[0].payload)
    assert "goal_id" not in repr(records[0].payload)


def test_scenario_adapter_serializes_ranked_aggregate_evidence_only() -> None:
    repository = AsyncMock(spec=ScenarioSimulationRepository)
    definition_id = uuid4()
    definition = SimpleNamespace(
        name="Lower expenses",
        kind="user_defined",
        evaluation_status="optimized",
        risk_status="available",
        reliability="normal",
        capacity_total=Decimal("1000"),
        allocated_total=Decimal("800"),
        unallocated_total=Decimal("200"),
        robustness_score=Decimal("85"),
        all_goals_completion_probability=Decimal("0.8"),
        all_deadlines_met_probability=Decimal("0.7"),
        reserve_coverage_probability=Decimal("0.9"),
        negative_savings_probability=Decimal("0.1"),
        constraint_feasibility_probability=Decimal("0.95"),
        tail_expected_shortfall_90=Decimal("100"),
    )
    comparison = SimpleNamespace(
        scenario_definition_id=definition_id,
        rank=1,
        recommended=True,
        decision_score=Decimal("88"),
        expected_capacity_delta=Decimal("100"),
        completion_probability_delta=Decimal("0.1"),
        deadline_probability_delta=Decimal("0.1"),
        expected_shortfall_delta=Decimal("-50"),
        tail_shortfall_delta=Decimal("-75"),
        reason_codes=["highest_safe_score"],
        sensitivity_signals=[{"factor": "expense_change", "influence_score": "100"}],
    )
    repository.get.return_value = SimpleNamespace(
        id=RESOURCE_ID,
        cutoff_at=NOW,
        currency="INR",
        definitions=(definition,),
        comparisons=(comparison,),
        snapshot_warnings=[],
        contract_version="2026.1",
        comparison_policy_version="2026.1",
        sensitivity_policy_version="2026.1",
        decision_policy_version="2026.1",
        risk_policy_version="2026.1",
    )

    records = asyncio.run(
        ScenarioEvidenceAdapter(repository).retrieve(
            AsyncMock(spec=AsyncSession),
            user_id=OWNER_ID,
            intent=AssistantIntent.COMPARE_SCENARIOS,
            query=AssistantEvidenceQuery(
                source=AssistantEvidenceSource.SCENARIO_SIMULATION,
                reference_id=RESOURCE_ID,
            ),
        )
    )

    assert records[0].payload["recommendation"] == str(definition_id)
    assert records[0].payload["comparisons"][0]["recommended"] is True
    assert "root_seed" not in records[0].payload
    assert "raw_samples" not in repr(records[0].payload)
