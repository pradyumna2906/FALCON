"""Owner-scoped contribution persistence tests."""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.goal_planning import (
    ContributionCreateCommand,
    ContributionRepository,
)
from falcon_api.models.enums import ContributionSourceType, TransactionStatus
from falcon_api.models.planning import GoalContribution


_NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)


def _session() -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.add = Mock()
    return session


def _command() -> ContributionCreateCommand:
    return ContributionCreateCommand(
        source_type=ContributionSourceType.MANUAL,
        amount=Decimal("1250.5000"),
        contribution_date=date(2026, 9, 1),
        transaction_id=None,
        note="  Deposit  ",
    )


def _compiled(statement) -> tuple[str, dict[str, object]]:
    compiled = statement.compile(dialect=postgresql.dialect())
    return str(compiled), compiled.params


def test_create_assigns_owner_provenance_and_exact_amount() -> None:
    session = _session()
    user_id = uuid4()
    goal_id = uuid4()

    result = asyncio.run(
        ContributionRepository().create(
            session,
            user_id=user_id,
            goal_id=goal_id,
            command=_command(),
            contribution_date=date(2026, 9, 1),
            now=_NOW,
        )
    )

    assert result.user_id == user_id
    assert result.goal_id == goal_id
    assert result.amount == Decimal("1250.5000")
    assert result.note == "Deposit"
    assert result.source_type is ContributionSourceType.MANUAL
    session.add.assert_called_once_with(result)
    session.flush.assert_awaited_once_with()


def test_list_and_get_require_owner_and_goal_identifiers() -> None:
    session = _session()
    scalar_rows = Mock()
    scalar_rows.all.return_value = []
    session.scalars.return_value = scalar_rows
    user_id = uuid4()
    goal_id = uuid4()
    contribution_id = uuid4()

    asyncio.run(
        ContributionRepository().list(
            session,
            user_id=user_id,
            goal_id=goal_id,
        )
    )
    list_sql, list_params = _compiled(session.scalars.await_args.args[0])
    asyncio.run(
        ContributionRepository().get(
            session,
            user_id=user_id,
            goal_id=goal_id,
            contribution_id=contribution_id,
            for_update=True,
        )
    )
    get_sql, get_params = _compiled(session.scalar.await_args.args[0])

    assert "goal_contributions.user_id =" in list_sql
    assert "goal_contributions.goal_id =" in list_sql
    assert "ORDER BY" in list_sql
    assert user_id in list_params.values()
    assert goal_id in list_params.values()
    assert "goal_contributions.id =" in get_sql
    assert "FOR UPDATE" in get_sql
    assert contribution_id in get_params.values()


def test_goal_and_transaction_sums_are_owner_scoped_and_cutoff_safe() -> None:
    session = _session()
    session.scalar.return_value = Decimal("2500")
    repository = ContributionRepository()
    user_id = uuid4()
    goal_id = uuid4()
    transaction_id = uuid4()

    assert asyncio.run(
        repository.sum_for_goal(
            session,
            user_id=user_id,
            goal_id=goal_id,
            cutoff_at=_NOW,
        )
    ) == Decimal("2500.0000")
    goal_sql, goal_params = _compiled(session.scalar.await_args.args[0])
    assert "created_at <=" in goal_sql and "updated_at <=" in goal_sql
    assert user_id in goal_params.values() and goal_id in goal_params.values()

    asyncio.run(
        repository.sum_for_transaction(
            session,
            user_id=user_id,
            transaction_id=transaction_id,
            excluding_contribution_id=uuid4(),
        )
    )
    transaction_sql, transaction_params = _compiled(
        session.scalar.await_args.args[0]
    )
    assert "transaction_id =" in transaction_sql
    assert "goal_contributions.id !=" in transaction_sql
    assert transaction_id in transaction_params.values()


def test_transaction_evidence_locks_only_owned_transaction() -> None:
    session = _session()
    result = Mock()
    result.mappings.return_value.one_or_none.return_value = {
        "id": uuid4(),
        "amount": Decimal("-5000"),
        "transaction_date": date(2026, 9, 3),
        "status": TransactionStatus.POSTED,
        "currency": "INR",
    }
    session.execute.return_value = result
    user_id = uuid4()

    evidence = asyncio.run(
        ContributionRepository().transaction_evidence_for_update(
            session,
            user_id=user_id,
            transaction_id=result.mappings.return_value.one_or_none.return_value[
                "id"
            ],
        )
    )
    sql, params = _compiled(session.execute.await_args.args[0])

    assert evidence is not None
    assert evidence.amount == Decimal("5000.0000")
    assert evidence.status is TransactionStatus.POSTED
    assert "transactions.user_id =" in sql
    assert "JOIN accounts" in sql
    assert "FOR UPDATE OF transactions" in sql
    assert user_id in params.values()


def test_transaction_evidence_can_be_absent_and_delete_flushes() -> None:
    session = _session()
    result = Mock()
    result.mappings.return_value.one_or_none.return_value = None
    session.execute.return_value = result
    repository = ContributionRepository()

    assert asyncio.run(
        repository.transaction_evidence_for_update(
            session,
            user_id=uuid4(),
            transaction_id=uuid4(),
        )
    ) is None

    contribution = Mock(spec=GoalContribution)
    asyncio.run(repository.delete(session, contribution=contribution))
    session.delete.assert_awaited_once_with(contribution)
    session.flush.assert_awaited_once_with()
