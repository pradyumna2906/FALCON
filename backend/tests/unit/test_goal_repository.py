"""Owner-scoped SQL and mutation contracts for goals."""

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.goal_planning import GoalRepository, GoalValues
from falcon_api.models.enums import GoalPriority, GoalStatus, GoalType
from falcon_api.models.planning import Goal


_NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)


def _session() -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.add = Mock()
    return session


def _values() -> GoalValues:
    return GoalValues(
        name="Education Fund",
        goal_type=GoalType.EDUCATION,
        target_amount=Decimal("200000.0000"),
        starting_amount=Decimal("25000.0000"),
        currency="INR",
        target_date=date(2028, 6, 1),
        priority=GoalPriority.HIGH,
        description="Semester fees",
    )


def _goal(*, user_id=None, status: GoalStatus = GoalStatus.ACTIVE) -> Goal:
    values = _values()
    return Goal(
        id=uuid4(),
        user_id=user_id or uuid4(),
        name=values.name,
        goal_type=values.goal_type,
        target_amount=values.target_amount,
        starting_amount=values.starting_amount,
        currency=values.currency,
        target_date=values.target_date,
        priority=values.priority,
        status=status,
        description=values.description,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _compiled(statement) -> tuple[str, dict[str, object]]:
    compiled = statement.compile(dialect=postgresql.dialect())
    return str(compiled), compiled.params


def test_create_assigns_trusted_owner_and_active_status() -> None:
    user_id = uuid4()
    session = _session()

    goal = asyncio.run(
        GoalRepository().create(
            session,
            user_id=user_id,
            values=_values(),
            now=_NOW,
        )
    )

    assert goal.user_id == user_id
    assert goal.status is GoalStatus.ACTIVE
    assert goal.currency == "INR"
    assert goal.created_at == _NOW
    session.add.assert_called_once_with(goal)
    session.flush.assert_awaited_once_with()


@pytest.mark.parametrize("for_update", [False, True])
def test_get_requires_both_owner_and_identifier(for_update: bool) -> None:
    session = _session()
    user_id = uuid4()
    goal_id = uuid4()
    asyncio.run(
        GoalRepository().get(
            session,
            user_id=user_id,
            goal_id=goal_id,
            for_update=for_update,
        )
    )

    query, params = _compiled(session.scalar.await_args.args[0])
    assert "goals.user_id =" in query
    assert "goals.id =" in query
    assert user_id in params.values()
    assert goal_id in params.values()
    assert ("FOR UPDATE" in query) is for_update


def test_list_is_owned_filtered_bounded_and_deterministic() -> None:
    session = _session()
    scalar_result = Mock()
    scalar_result.all.return_value = []
    session.scalars.return_value = scalar_result
    user_id = uuid4()

    result = asyncio.run(
        GoalRepository().list(
            session,
            user_id=user_id,
            status=GoalStatus.ACTIVE,
            limit=25,
        )
    )

    query, params = _compiled(session.scalars.await_args.args[0])
    assert result == ()
    assert "goals.user_id =" in query
    assert "goals.status =" in query
    assert "ORDER BY CASE" in query
    assert "goals.target_date ASC" in query
    assert "LIMIT" in query
    assert user_id in params.values()
    assert 25 in params.values()


def test_list_can_include_every_lifecycle_state() -> None:
    session = _session()
    scalar_result = Mock()
    scalar_result.all.return_value = []
    session.scalars.return_value = scalar_result

    asyncio.run(
        GoalRepository().list(
            session,
            user_id=uuid4(),
            status=None,
            limit=100,
        )
    )

    query, _ = _compiled(session.scalars.await_args.args[0])
    where_clause = query.split("ORDER BY", maxsplit=1)[0]
    assert "goals.status =" not in where_clause


def test_replace_and_transition_mutate_owned_goal() -> None:
    user_id = uuid4()
    session = _session()
    goal = _goal(user_id=user_id)
    values = replace(
        _values(),
        name="Updated Goal",
        priority=GoalPriority.CRITICAL,
    )

    replaced = asyncio.run(
        GoalRepository().replace(
            session,
            user_id=user_id,
            goal=goal,
            values=values,
            now=_NOW,
        )
    )
    transitioned = asyncio.run(
        GoalRepository().transition(
            session,
            user_id=user_id,
            goal=goal,
            status=GoalStatus.COMPLETED,
            now=_NOW,
        )
    )

    assert replaced is goal
    assert transitioned is goal
    assert goal.name == "Updated Goal"
    assert goal.priority is GoalPriority.CRITICAL
    assert goal.status is GoalStatus.COMPLETED
    assert session.flush.await_count == 2


@pytest.mark.parametrize("operation", ["replace", "transition"])
def test_mutations_reject_an_object_from_another_owner(operation: str) -> None:
    repository = GoalRepository()
    session = _session()
    goal = _goal()
    kwargs = {
        "session": session,
        "user_id": uuid4(),
        "goal": goal,
        "now": _NOW,
    }
    if operation == "replace":
        kwargs["values"] = _values()
    else:
        kwargs["status"] = GoalStatus.CANCELLED

    with pytest.raises(ValueError, match="does not belong"):
        asyncio.run(getattr(repository, operation)(**kwargs))

    session.flush.assert_not_awaited()
