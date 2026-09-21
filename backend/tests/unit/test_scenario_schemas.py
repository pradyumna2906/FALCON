"""Tests for the authenticated Phase 11 request boundary."""

from pydantic import ValidationError
import pytest

from falcon_api.schemas.scenarios import ScenarioSimulationDraftRequest
from goal_plan_test_data import GOAL_ID


def _payload() -> dict[str, object]:
    return {
        "source_plan_id": "40000000-0000-4000-8000-000000000001",
        "scenarios": [
            {
                "name": "Income shock",
                "income_change_percent": "-15",
                "one_time_expenses": [
                    {"period_start": "2026-10-01", "amount": "5000"}
                ],
                "recurring_expense_adjustments": [
                    {
                        "start_period": "2026-10-01",
                        "end_period": "2026-11-01",
                        "monthly_delta": "250",
                    }
                ],
                "debt_payment_adjustments": [
                    {
                        "start_period": "2026-10-01",
                        "end_period": "2026-11-01",
                        "monthly_delta": "100",
                    }
                ],
                "income_interruptions": [
                    {
                        "start_period": "2026-11-01",
                        "end_period": "2026-11-01",
                        "retained_income_percent": "25",
                    }
                ],
                "goal_adjustments": [
                    {
                        "goal_id": str(GOAL_ID),
                        "target_date": "2027-03-31",
                    }
                ],
            }
        ],
    }


def test_draft_request_accepts_only_bounded_hypothetical_inputs() -> None:
    request = ScenarioSimulationDraftRequest.model_validate(_payload())
    scenario = request.to_domain()[0]

    assert scenario.name == "Income shock"
    assert str(scenario.income_change_percent) == "-15.0000"
    assert scenario.goal_adjustments[0].goal_id == GOAL_ID
    assert str(scenario.debt_payment_adjustments[0].monthly_delta) == "100.0000"


@pytest.mark.parametrize(
    "server_field",
    [
        "user_id",
        "cutoff_at",
        "policy_version",
        "random_generator",
        "forecast_values",
        "source_balance",
    ],
)
def test_draft_request_rejects_server_owned_fields(server_field: str) -> None:
    payload = _payload()
    payload[server_field] = "untrusted"
    with pytest.raises(ValidationError):
        ScenarioSimulationDraftRequest.model_validate(payload)


def test_draft_request_rejects_empty_duplicate_and_malformed_scenarios() -> None:
    payload = _payload()
    payload["scenarios"] = []
    with pytest.raises(ValidationError):
        ScenarioSimulationDraftRequest.model_validate(payload)

    payload = _payload()
    payload["scenarios"] = [payload["scenarios"][0], payload["scenarios"][0]]
    with pytest.raises(ValidationError, match="unique"):
        ScenarioSimulationDraftRequest.model_validate(payload)

    payload = _payload()
    payload["scenarios"][0]["one_time_expenses"][0]["period_start"] = "2026-10-02"
    with pytest.raises(ValidationError, match="month boundary"):
        ScenarioSimulationDraftRequest.model_validate(payload)


def test_draft_request_is_deeply_immutable() -> None:
    request = ScenarioSimulationDraftRequest.model_validate(_payload())
    with pytest.raises(ValidationError, match="frozen"):
        request.source_plan_id = GOAL_ID
    with pytest.raises(ValidationError, match="frozen"):
        request.scenarios[0].name = "Changed"
