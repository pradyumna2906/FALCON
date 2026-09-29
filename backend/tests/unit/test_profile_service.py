"""Unit contracts for financial-profile application workflows."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.auth.clock import Clock
from falcon_api.core.errors import ApplicationError
from falcon_api.models.enums import (
    IncomePattern,
    IncomeStability,
    ProfileCompletionStatus,
)
from falcon_api.models.user import FinancialProfile
from falcon_api.profile import (
    FinancialProfileCommand,
    FinancialProfileRepository,
    FinancialProfileService,
)


_NOW = datetime(2026, 8, 19, 21, 0, tzinfo=UTC)


def _clock() -> Mock:
    clock = Mock(spec=Clock)
    clock.now.return_value = _NOW
    return clock


def _repository() -> AsyncMock:
    return AsyncMock(spec=FinancialProfileRepository)


def _session() -> AsyncMock:
    nested = AsyncMock()
    nested.__aenter__.return_value = nested
    nested.__aexit__.return_value = False

    session = AsyncMock(spec=AsyncSession)
    session.begin_nested = Mock(return_value=nested)
    return session


def _service(
    repository: AsyncMock,
) -> FinancialProfileService:
    return FinancialProfileService(
        repository=repository,
        clock=_clock(),
    )


def _command(
    *,
    income_pattern: IncomePattern | None = IncomePattern.SALARIED,
    income_stability: IncomeStability | None = IncomeStability.STABLE,
) -> FinancialProfileCommand:
    return FinancialProfileCommand(
        income_pattern=income_pattern,
        income_stability=income_stability,
        has_household_responsibilities=True,
        dependant_count=2,
        emergency_fund_target_months=Decimal("6.00"),
    )


def _profile(user_id: UUID) -> FinancialProfile:
    return FinancialProfile(
        id=uuid4(),
        user_id=user_id,
        income_pattern=IncomePattern.SALARIED,
        income_stability=IncomeStability.STABLE,
        has_household_responsibilities=True,
        dependant_count=2,
        emergency_fund_target_months=Decimal("6.00"),
        completion_status=ProfileCompletionStatus.COMPLETE,
        created_at=_NOW - timedelta(days=1),
        updated_at=_NOW,
    )


def _integrity_error(constraint_name: str) -> IntegrityError:
    original = Mock()
    original.diag.constraint_name = constraint_name
    return IntegrityError("INSERT financial_profiles", {}, original)


def test_get_returns_user_owned_profile() -> None:
    user_id = uuid4()
    profile = _profile(user_id)
    repository = _repository()
    repository.get_by_user_id.return_value = profile
    session = Mock()

    result = asyncio.run(
        _service(repository).get(session, user_id=user_id)
    )

    assert result is profile
    repository.get_by_user_id.assert_awaited_once_with(
        session,
        user_id=user_id,
    )


def test_get_raises_public_error_when_profile_is_missing() -> None:
    repository = _repository()
    repository.get_by_user_id.return_value = None

    with pytest.raises(ApplicationError) as exc_info:
        asyncio.run(
            _service(repository).get(Mock(), user_id=uuid4())
        )

    assert exc_info.value.code == "profile_not_found"
    assert exc_info.value.status_code == 404
    assert exc_info.value.public_message == (
        "A financial profile has not been created."
    )


@pytest.mark.parametrize(
    ("income_pattern", "income_stability", "expected"),
    [
        (
            IncomePattern.SALARIED,
            IncomeStability.STABLE,
            ProfileCompletionStatus.COMPLETE,
        ),
        (None, IncomeStability.STABLE, ProfileCompletionStatus.DRAFT),
        (IncomePattern.MIXED, None, ProfileCompletionStatus.DRAFT),
        (None, None, ProfileCompletionStatus.DRAFT),
    ],
)
def test_put_derives_completion_status(
    income_pattern: IncomePattern | None,
    income_stability: IncomeStability | None,
    expected: ProfileCompletionStatus,
) -> None:
    user_id = uuid4()
    repository = _repository()
    repository.get_by_user_id.return_value = _profile(user_id)
    repository.replace.return_value = _profile(user_id)

    asyncio.run(
        _service(repository).put(
            _session(),
            user_id=user_id,
            command=_command(
                income_pattern=income_pattern,
                income_stability=income_stability,
            ),
        )
    )

    values = repository.replace.await_args.kwargs["values"]
    assert values.completion_status is expected


def test_put_replaces_existing_locked_profile() -> None:
    user_id = uuid4()
    existing = _profile(user_id)
    replaced = _profile(user_id)
    repository = _repository()
    repository.get_by_user_id.return_value = existing
    repository.replace.return_value = replaced
    session = _session()

    result = asyncio.run(
        _service(repository).put(
            session,
            user_id=user_id,
            command=_command(),
        )
    )

    repository.get_by_user_id.assert_awaited_once_with(
        session,
        user_id=user_id,
        for_update=True,
    )
    assert repository.replace.await_args.args == (session,)
    replace = repository.replace.await_args.kwargs
    assert replace["user_id"] == user_id
    assert replace["profile"] is existing
    assert replace["now"] == _NOW
    assert result.profile is replaced
    assert result.created is False
    repository.create.assert_not_awaited()
    session.begin_nested.assert_not_called()


def test_put_creates_profile_inside_savepoint_when_missing() -> None:
    user_id = uuid4()
    created = _profile(user_id)
    repository = _repository()
    repository.get_by_user_id.return_value = None
    repository.create.return_value = created
    session = _session()

    result = asyncio.run(
        _service(repository).put(
            session,
            user_id=user_id,
            command=_command(),
        )
    )

    session.begin_nested.assert_called_once_with()
    assert repository.create.await_args.args == (session,)
    create = repository.create.await_args.kwargs
    assert create["user_id"] == user_id
    assert create["now"] == _NOW
    assert result.profile is created
    assert result.created is True
    repository.replace.assert_not_awaited()


def test_put_replaces_row_after_concurrent_creation() -> None:
    user_id = uuid4()
    competing = _profile(user_id)
    replaced = _profile(user_id)
    repository = _repository()
    repository.get_by_user_id.side_effect = [None, competing]
    repository.create.side_effect = _integrity_error(
        "uq_financial_profiles_user_id"
    )
    repository.replace.return_value = replaced
    session = _session()

    result = asyncio.run(
        _service(repository).put(
            session,
            user_id=user_id,
            command=_command(),
        )
    )

    assert repository.get_by_user_id.await_count == 2
    second_lookup = repository.get_by_user_id.await_args_list[1]
    assert second_lookup.kwargs == {
        "user_id": user_id,
        "for_update": True,
    }
    assert repository.replace.await_args.kwargs["profile"] is competing
    assert result.profile is replaced
    assert result.created is False


def test_put_preserves_unrelated_integrity_error() -> None:
    repository = _repository()
    repository.get_by_user_id.return_value = None
    failure = _integrity_error("ck_unrelated")
    repository.create.side_effect = failure

    with pytest.raises(IntegrityError) as exc_info:
        asyncio.run(
            _service(repository).put(
                _session(),
                user_id=uuid4(),
                command=_command(),
            )
        )

    assert exc_info.value is failure
    assert repository.get_by_user_id.await_count == 1
    repository.replace.assert_not_awaited()


def test_put_preserves_race_error_when_row_cannot_be_reloaded() -> None:
    repository = _repository()
    repository.get_by_user_id.side_effect = [None, None]
    failure = _integrity_error("uq_financial_profiles_user_id")
    repository.create.side_effect = failure

    with pytest.raises(IntegrityError) as exc_info:
        asyncio.run(
            _service(repository).put(
                _session(),
                user_id=uuid4(),
                command=_command(),
            )
        )

    assert exc_info.value is failure
    repository.replace.assert_not_awaited()
