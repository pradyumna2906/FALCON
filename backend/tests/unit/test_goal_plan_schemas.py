"""Strict public contracts for persistent Phase 10 plans."""

import pytest
from pydantic import ValidationError

from falcon_api.models.enums import GoalPlanStatus
from falcon_api.schemas.goal_plans import (
    GoalPlanGenerationRequest,
    GoalPlanListResponse,
    GoalPlanRunResponse,
    GoalPlanSummaryResponse,
)
from goal_plan_test_data import transient_goal_plan_run


def test_generation_request_normalizes_currency_and_forbids_server_fields() -> None:
    assert GoalPlanGenerationRequest(currency=" inr ").currency == "INR"
    assert GoalPlanGenerationRequest().currency is None

    for payload in (
        {"currency": "RUPEE"},
        {"owner_id": "10000000-0000-4000-8000-000000000001"},
        {"planning_cutoff_at": "2026-09-15T12:00:00Z"},
        {"solver": "custom"},
        {"emergency_reserve_amount": "0"},
    ):
        with pytest.raises(ValidationError):
            GoalPlanGenerationRequest.model_validate(payload)


def test_generation_request_is_immutable() -> None:
    request = GoalPlanGenerationRequest(currency="INR")

    with pytest.raises(ValidationError, match="frozen"):
        request.currency = "USD"


def test_plan_response_reconciles_complete_immutable_graph() -> None:
    run = transient_goal_plan_run()

    response = GoalPlanRunResponse.model_validate(run)
    payload = response.model_dump(mode="json")

    assert response.status is GoalPlanStatus.GENERATED
    assert response.successor_plan_id is None
    assert response.decided_at is None
    assert response.goal_count == len(response.outcomes) == 1
    assert len(response.periods) == 2
    assert response.available_savings == (
        response.allocated_savings + response.unallocated_savings
    )
    assert response.periods[-1].allocations[0].cumulative_amount == (
        response.outcomes[0].allocated_amount
    )
    serialized = repr(payload)
    assert "user_id" not in serialized
    assert "'liquid_balance':" not in serialized
    assert "'outstanding_debt':" not in serialized
    assert "'transaction_id':" not in serialized.lower()


def test_plan_summary_and_bounded_list_hide_schedule_details() -> None:
    run = transient_goal_plan_run()
    summary = GoalPlanSummaryResponse.model_validate(run)
    response = GoalPlanListResponse(items=(summary,))
    payload = response.model_dump(mode="json")

    assert payload["items"][0]["id"] == str(run.id)
    assert "outcomes" not in payload["items"][0]
    assert "periods" not in payload["items"][0]
    assert "events" not in payload["items"][0]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("deterministic_plan_id", "not-a-hash"),
        ("currency", "RUPEE"),
        ("available_savings", "12345678901234567890.0000"),
    ],
)
def test_plan_response_rejects_malformed_persistent_values(field, value) -> None:
    run = transient_goal_plan_run()
    setattr(run, field, value)

    with pytest.raises(ValidationError):
        GoalPlanRunResponse.model_validate(run)


def test_plan_response_rejects_out_of_range_probability() -> None:
    run = transient_goal_plan_run()
    run.outcomes[0].completion_probability = 2

    with pytest.raises(ValidationError, match="less than or equal to 1"):
        GoalPlanRunResponse.model_validate(run)
