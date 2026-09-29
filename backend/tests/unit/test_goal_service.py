"""Application policy tests for authenticated goal management."""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.core.errors import ApplicationError
from falcon_api.goal_planning import (
    GoalCreateCommand,
    GoalRepository,
    GoalService,
    GoalUpdateCommand,
)
from falcon_api.models.enums import GoalPriority, GoalStatus, GoalType
from falcon_api.models.planning import Goal


_NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return _NOW


def _session() -> AsyncMock:
    return AsyncMock(spec=AsyncSession)


def _command(**changes: object) -> GoalCreateCommand:
    values: dict[str, object] = {
        "name": "Education Fund",
        "goal_type": GoalType.EDUCATION,
        "target_amount": Decimal("200000.0000"),
        "starting_amount": Decimal("25000.0000"),
        "currency": None,
        "target_date": date(2028, 6, 1),
        "priority": GoalPriority.HIGH,
        "description": "Semester fees",
    }
    values.update(changes)
    return GoalCreateCommand(**values)


def _goal(
    *,
    user_id=None,
    status: GoalStatus = GoalStatus.ACTIVE,
) -> Goal:
    return Goal(
        id=uuid4(),
        user_id=user_id or uuid4(),
        name="Education Fund",
        goal_type=GoalType.EDUCATION,
        target_amount=Decimal("200000.0000"),
        starting_amount=Decimal("25000.0000"),
        currency="INR",
        target_date=date(2028, 6, 1),
        priority=GoalPriority.HIGH,
        status=status,
        description="Semester fees",
        created_at=_NOW,
        updated_at=_NOW,
    )


def _service(repository: AsyncMock) -> GoalService:
    return GoalService(repository=repository, clock=FixedClock())


def test_create_uses_principal_owner_timezone_and_default_currency() -> None:
    repository = AsyncMock(spec=GoalRepository)
    expected = _goal()
    repository.create.return_value = expected
    service = _service(repository)
    user_id = uuid4()

    result = asyncio.run(
        service.create(
            _session(),
            user_id=user_id,
            default_currency="inr",
            trusted_timezone="Asia/Kolkata",
            command=_command(name="  Education Fund  ", description="  Fees  "),
        )
    )

    assert result is expected
    call = repository.create.await_args
    assert call.kwargs["user_id"] == user_id
    assert call.kwargs["now"] == _NOW
    assert call.kwargs["values"].currency == "INR"
    assert call.kwargs["values"].name == "Education Fund"
    assert call.kwargs["values"].description == "Fees"


def test_create_honors_an_explicit_normalized_currency() -> None:
    repository = AsyncMock(spec=GoalRepository)
    repository.create.return_value = _goal()

    asyncio.run(
        _service(repository).create(
            _session(),
            user_id=uuid4(),
            default_currency="INR",
            trusted_timezone="UTC",
            command=_command(currency="usd"),
        )
    )

    assert repository.create.await_args.kwargs["values"].currency == "USD"


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"name": "   "}, "goal_invalid_name"),
        ({"target_amount": Decimal("0")}, "goal_invalid_amount"),
        ({"starting_amount": Decimal("-1")}, "goal_invalid_amount"),
        ({"starting_amount": Decimal("200001")}, "goal_invalid_amount"),
        ({"target_amount": Decimal("NaN")}, "goal_invalid_amount"),
        ({"target_date": date(2026, 9, 14)}, "goal_invalid_deadline"),
    ],
)
def test_create_rejects_invalid_domain_values(
    changes: dict[str, object],
    code: str,
) -> None:
    repository = AsyncMock(spec=GoalRepository)

    with pytest.raises(ApplicationError) as captured:
        asyncio.run(
            _service(repository).create(
                _session(),
                user_id=uuid4(),
                default_currency="INR",
                trusted_timezone="UTC",
                command=_command(**changes),
            )
        )

    assert captured.value.code == code
    assert captured.value.status_code == 422
    repository.create.assert_not_awaited()


def test_get_returns_owned_goal_and_hides_missing_or_foreign_goal() -> None:
    repository = AsyncMock(spec=GoalRepository)
    expected = _goal()
    repository.get.side_effect = [expected, None]
    service = _service(repository)
    session = _session()
    user_id = uuid4()
    goal_id = uuid4()

    assert (
        asyncio.run(
            service.get(session, user_id=user_id, goal_id=goal_id)
        )
        is expected
    )
    with pytest.raises(ApplicationError) as captured:
        asyncio.run(service.get(session, user_id=user_id, goal_id=uuid4()))

    assert captured.value.code == "goal_not_found"
    assert captured.value.status_code == 404


def test_list_delegates_owner_filter_and_bound() -> None:
    repository = AsyncMock(spec=GoalRepository)
    repository.list.return_value = (_goal(),)
    service = _service(repository)
    user_id = uuid4()
    session = _session()

    result = asyncio.run(
        service.list(
            session,
            user_id=user_id,
            status=GoalStatus.ACTIVE,
            limit=25,
        )
    )

    assert len(result) == 1
    repository.list.assert_awaited_once_with(
        session,
        user_id=user_id,
        status=GoalStatus.ACTIVE,
        limit=25,
    )


def test_update_locks_and_merges_only_supplied_fields() -> None:
    user_id = uuid4()
    goal = _goal(user_id=user_id)
    repository = AsyncMock(spec=GoalRepository)
    repository.get.return_value = goal
    repository.replace.return_value = goal
    service = _service(repository)
    command = GoalUpdateCommand(
        fields=frozenset({"target_amount", "priority", "description"}),
        target_amount=Decimal("250000.0000"),
        priority=GoalPriority.CRITICAL,
        description="  Updated fees  ",
    )

    result = asyncio.run(
        service.update(
            _session(),
            user_id=user_id,
            goal_id=goal.id,
            trusted_timezone="Asia/Kolkata",
            command=command,
        )
    )

    assert result is goal
    repository.get.assert_awaited_once()
    assert repository.get.await_args.kwargs["for_update"] is True
    values = repository.replace.await_args.kwargs["values"]
    assert values.target_amount == Decimal("250000.0000")
    assert values.priority is GoalPriority.CRITICAL
    assert values.description == "Updated fees"
    assert values.name == goal.name
    assert values.currency == goal.currency


def test_update_can_clear_description_and_normalize_currency() -> None:
    user_id = uuid4()
    goal = _goal(user_id=user_id)
    repository = AsyncMock(spec=GoalRepository)
    repository.get.return_value = goal
    repository.replace.return_value = goal

    asyncio.run(
        _service(repository).update(
            _session(),
            user_id=user_id,
            goal_id=goal.id,
            trusted_timezone="UTC",
            command=GoalUpdateCommand(
                fields=frozenset({"description", "currency"}),
                description=None,
                currency="usd",
            ),
        )
    )

    values = repository.replace.await_args.kwargs["values"]
    assert values.description is None
    assert values.currency == "USD"


def test_update_revalidates_merged_amounts_and_deadline() -> None:
    goal = _goal()
    repository = AsyncMock(spec=GoalRepository)
    repository.get.return_value = goal
    service = _service(repository)

    for command, code in (
        (
            GoalUpdateCommand(
                fields=frozenset({"target_amount"}),
                target_amount=Decimal("20000"),
            ),
            "goal_invalid_amount",
        ),
        (
            GoalUpdateCommand(
                fields=frozenset({"target_date"}),
                target_date=date(2026, 9, 14),
            ),
            "goal_invalid_deadline",
        ),
    ):
        with pytest.raises(ApplicationError) as captured:
            asyncio.run(
                service.update(
                    _session(),
                    user_id=goal.user_id,
                    goal_id=goal.id,
                    trusted_timezone="UTC",
                    command=command,
                )
            )
        assert captured.value.code == code

    repository.replace.assert_not_awaited()


def test_update_and_transition_reject_terminal_goals() -> None:
    goal = _goal(status=GoalStatus.COMPLETED)
    repository = AsyncMock(spec=GoalRepository)
    repository.get.return_value = goal
    service = _service(repository)

    with pytest.raises(ApplicationError) as update_error:
        asyncio.run(
            service.update(
                _session(),
                user_id=goal.user_id,
                goal_id=goal.id,
                trusted_timezone="UTC",
                command=GoalUpdateCommand(
                    fields=frozenset({"priority"}),
                    priority=GoalPriority.LOW,
                ),
            )
        )
    with pytest.raises(ApplicationError) as transition_error:
        asyncio.run(
            service.cancel(
                _session(),
                user_id=goal.user_id,
                goal_id=goal.id,
            )
        )

    assert update_error.value.code == "goal_inactive"
    assert transition_error.value.code == "goal_inactive"
    repository.replace.assert_not_awaited()
    repository.transition.assert_not_awaited()


@pytest.mark.parametrize(
    ("method", "expected"),
    [("complete", GoalStatus.COMPLETED), ("cancel", GoalStatus.CANCELLED)],
)
def test_terminal_transition_is_locked_and_service_owned(
    method: str,
    expected: GoalStatus,
) -> None:
    goal = _goal()
    repository = AsyncMock(spec=GoalRepository)
    repository.get.return_value = goal
    repository.transition.return_value = goal
    service = _service(repository)

    result = asyncio.run(
        getattr(service, method)(
            _session(),
            user_id=goal.user_id,
            goal_id=goal.id,
        )
    )

    assert result is goal
    assert repository.get.await_args.kwargs["for_update"] is True
    assert repository.transition.await_args.kwargs["status"] is expected
    assert repository.transition.await_args.kwargs["now"] == _NOW


def test_locked_lookup_uses_same_not_found_contract() -> None:
    repository = AsyncMock(spec=GoalRepository)
    repository.get.return_value = None

    with pytest.raises(ApplicationError) as captured:
        asyncio.run(
            _service(repository).complete(
                _session(),
                user_id=uuid4(),
                goal_id=uuid4(),
            )
        )

    assert captured.value.code == "goal_not_found"
