"""Contribution provenance, allocation, and progress service tests."""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from falcon_api.core.errors import ApplicationError
from falcon_api.goal_planning import (
    ContributionCreateCommand,
    ContributionRepository,
    ContributionService,
    GoalRepository,
)
from falcon_api.goal_planning.contributions import TransactionAllocationEvidence
from falcon_api.models.enums import (
    ContributionSourceType,
    GoalPriority,
    GoalStatus,
    GoalType,
    TransactionStatus,
)
from falcon_api.models.planning import Goal, GoalContribution


_NOW = datetime(2026, 9, 14, 12, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return _NOW


def _goal(*, status: GoalStatus = GoalStatus.ACTIVE) -> Goal:
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
        status=status,
        description=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _command(**changes: object) -> ContributionCreateCommand:
    values: dict[str, object] = {
        "source_type": ContributionSourceType.MANUAL,
        "amount": Decimal("2000"),
        "contribution_date": date(2026, 9, 1),
        "transaction_id": None,
        "note": "  Monthly deposit  ",
    }
    values.update(changes)
    return ContributionCreateCommand(**values)


def _service():
    contribution_repository = AsyncMock(spec=ContributionRepository)
    goal_repository = AsyncMock(spec=GoalRepository)
    service = ContributionService(
        repository=contribution_repository,
        goal_repository=goal_repository,
        clock=FixedClock(),
    )
    return service, contribution_repository, goal_repository


def test_manual_contribution_locks_goal_and_uses_trusted_owner() -> None:
    service, repository, goals = _service()
    goal = _goal()
    expected = AsyncMock(spec=GoalContribution)
    goals.get.return_value = goal
    repository.sum_for_goal.return_value = Decimal("1000")
    repository.create.return_value = expected

    result = asyncio.run(
        service.create(
            AsyncMock(),
            user_id=goal.user_id,
            goal_id=goal.id,
            trusted_timezone="Asia/Kolkata",
            command=_command(),
        )
    )

    assert result is expected
    assert goals.get.await_args.kwargs["for_update"] is True
    call = repository.create.await_args
    assert call.kwargs["user_id"] == goal.user_id
    assert call.kwargs["goal_id"] == goal.id
    assert call.kwargs["contribution_date"] == date(2026, 9, 1)
    assert call.kwargs["now"] == _NOW


@pytest.mark.parametrize(
    ("command", "code"),
    [
        (_command(amount=Decimal("NaN")), "goal_invalid_contribution"),
        (_command(amount=Decimal("0")), "goal_invalid_contribution"),
        (
            _command(contribution_date=date(2026, 9, 15)),
            "goal_invalid_contribution",
        ),
        (
            _command(contribution_date=None),
            "goal_invalid_contribution",
        ),
        (
            _command(transaction_id=uuid4()),
            "goal_invalid_contribution",
        ),
    ],
)
def test_manual_contribution_rejects_invalid_evidence(
    command: ContributionCreateCommand,
    code: str,
) -> None:
    service, repository, goals = _service()
    goal = _goal()
    goals.get.return_value = goal

    with pytest.raises(ApplicationError) as captured:
        asyncio.run(
            service.create(
                AsyncMock(),
                user_id=goal.user_id,
                goal_id=goal.id,
                trusted_timezone="UTC",
                command=command,
            )
        )

    assert captured.value.code == code
    repository.create.assert_not_awaited()


def test_contribution_cannot_exceed_goal_remaining_amount() -> None:
    service, repository, goals = _service()
    goal = _goal()
    goals.get.return_value = goal
    repository.sum_for_goal.return_value = Decimal("8000")

    with pytest.raises(ApplicationError) as captured:
        asyncio.run(
            service.create(
                AsyncMock(),
                user_id=goal.user_id,
                goal_id=goal.id,
                trusted_timezone="UTC",
                command=_command(),
            )
        )

    assert captured.value.code == "goal_contribution_exceeds_remaining"
    assert captured.value.status_code == 409


def test_transaction_contribution_derives_date_and_checks_allocation() -> None:
    service, repository, goals = _service()
    goal = _goal()
    transaction_id = uuid4()
    goals.get.return_value = goal
    repository.transaction_evidence_for_update.return_value = (
        TransactionAllocationEvidence(
            transaction_id=transaction_id,
            amount=Decimal("5000"),
            transaction_date=date(2026, 9, 7),
            currency="INR",
            status=TransactionStatus.POSTED,
        )
    )
    repository.sum_for_transaction.return_value = Decimal("1000")
    repository.sum_for_goal.return_value = Decimal("1000")
    repository.create.return_value = AsyncMock(spec=GoalContribution)
    command = _command(
        source_type=ContributionSourceType.TRANSACTION,
        transaction_id=transaction_id,
        contribution_date=None,
        amount=Decimal("3000"),
    )

    asyncio.run(
        service.create(
            AsyncMock(),
            user_id=goal.user_id,
            goal_id=goal.id,
            trusted_timezone="UTC",
            command=command,
        )
    )

    assert repository.create.await_args.kwargs["contribution_date"] == date(
        2026, 9, 7
    )


@pytest.mark.parametrize(
    ("evidence", "allocated", "code"),
    [
        (None, Decimal("0"), "goal_invalid_contribution"),
        (
            TransactionAllocationEvidence(
                transaction_id=uuid4(),
                amount=Decimal("5000"),
                transaction_date=date(2026, 9, 1),
                currency="INR",
                status=TransactionStatus.PENDING,
            ),
            Decimal("0"),
            "goal_invalid_contribution",
        ),
        (
            TransactionAllocationEvidence(
                transaction_id=uuid4(),
                amount=Decimal("5000"),
                transaction_date=date(2026, 9, 1),
                currency="USD",
                status=TransactionStatus.POSTED,
            ),
            Decimal("0"),
            "goal_currency_mismatch",
        ),
        (
            TransactionAllocationEvidence(
                transaction_id=uuid4(),
                amount=Decimal("2500"),
                transaction_date=date(2026, 9, 1),
                currency="INR",
                status=TransactionStatus.POSTED,
            ),
            Decimal("1000"),
            "goal_transaction_overallocated",
        ),
        (
            TransactionAllocationEvidence(
                transaction_id=uuid4(),
                amount=Decimal("5000"),
                transaction_date=date(2026, 9, 15),
                currency="INR",
                status=TransactionStatus.POSTED,
            ),
            Decimal("0"),
            "goal_invalid_contribution",
        ),
    ],
)
def test_transaction_contribution_fails_closed(
    evidence: TransactionAllocationEvidence | None,
    allocated: Decimal,
    code: str,
) -> None:
    service, repository, goals = _service()
    goal = _goal()
    transaction_id = uuid4()
    goals.get.return_value = goal
    repository.transaction_evidence_for_update.return_value = evidence
    repository.sum_for_transaction.return_value = allocated

    with pytest.raises(ApplicationError) as captured:
        asyncio.run(
            service.create(
                AsyncMock(),
                user_id=goal.user_id,
                goal_id=goal.id,
                trusted_timezone="UTC",
                command=_command(
                    source_type=ContributionSourceType.TRANSACTION,
                    transaction_id=transaction_id,
                    contribution_date=None,
                ),
            )
        )

    assert captured.value.code == code
    repository.create.assert_not_awaited()


def test_missing_or_terminal_goal_is_hidden_or_immutable() -> None:
    service, repository, goals = _service()
    goals.get.side_effect = [None, _goal(status=GoalStatus.COMPLETED)]

    for expected in ("goal_not_found", "goal_inactive"):
        with pytest.raises(ApplicationError) as captured:
            asyncio.run(
                service.create(
                    AsyncMock(),
                    user_id=uuid4(),
                    goal_id=uuid4(),
                    trusted_timezone="UTC",
                    command=_command(),
                )
            )
        assert captured.value.code == expected

    repository.create.assert_not_awaited()


def test_list_requires_owned_goal_and_returns_deterministic_rows() -> None:
    service, repository, goals = _service()
    goal = _goal()
    expected = (AsyncMock(spec=GoalContribution),)
    goals.get.return_value = goal
    repository.list.return_value = expected

    result = asyncio.run(
        service.list(AsyncMock(), user_id=goal.user_id, goal_id=goal.id)
    )

    assert result is expected
    repository.list.assert_awaited_once()


def test_delete_locks_linked_transaction_and_rejects_missing_contribution() -> None:
    service, repository, goals = _service()
    goal = _goal()
    contribution = AsyncMock(spec=GoalContribution)
    contribution.transaction_id = uuid4()
    goals.get.return_value = goal
    repository.get.side_effect = [contribution, None]

    asyncio.run(
        service.delete(
            AsyncMock(),
            user_id=goal.user_id,
            goal_id=goal.id,
            contribution_id=uuid4(),
        )
    )
    with pytest.raises(ApplicationError) as captured:
        asyncio.run(
            service.delete(
                AsyncMock(),
                user_id=goal.user_id,
                goal_id=goal.id,
                contribution_id=uuid4(),
            )
        )

    assert repository.transaction_evidence_for_update.await_count == 1
    assert repository.delete.await_count == 1
    assert captured.value.code == "goal_contribution_not_found"


def test_progress_uses_contributions_and_trusted_local_date() -> None:
    service, repository, goals = _service()
    goal = _goal()
    goals.get.return_value = goal
    repository.sum_for_goal.return_value = Decimal("2000")

    result = asyncio.run(
        service.progress(
            AsyncMock(),
            user_id=goal.user_id,
            goal_id=goal.id,
            trusted_timezone="Asia/Kolkata",
        )
    )

    assert result.current_amount == Decimal("3000.0000")
    assert result.calculated_on == date(2026, 9, 14)
