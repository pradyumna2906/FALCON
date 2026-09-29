"""Unit contracts for user-scoped financial-profile persistence."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.models.enums import (
    IncomePattern,
    IncomeStability,
    ProfileCompletionStatus,
)
from falcon_api.models.user import FinancialProfile
from falcon_api.profile import (
    FinancialProfileRepository,
    FinancialProfileValues,
)


_NOW = datetime(2026, 8, 19, 20, 0, tzinfo=UTC)


def _session() -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.add = Mock()
    return session


def _values(
    *,
    completion_status: ProfileCompletionStatus = (
        ProfileCompletionStatus.COMPLETE
    ),
) -> FinancialProfileValues:
    return FinancialProfileValues(
        income_pattern=IncomePattern.SALARIED,
        income_stability=IncomeStability.STABLE,
        has_household_responsibilities=True,
        dependant_count=2,
        emergency_fund_target_months=Decimal("6.00"),
        completion_status=completion_status,
    )


def _profile(user_id: UUID) -> FinancialProfile:
    return FinancialProfile(
        id=uuid4(),
        user_id=user_id,
        income_pattern=IncomePattern.IRREGULAR,
        income_stability=IncomeStability.UNSTABLE,
        has_household_responsibilities=False,
        dependant_count=0,
        emergency_fund_target_months=None,
        completion_status=ProfileCompletionStatus.DRAFT,
        created_at=_NOW - timedelta(days=1),
        updated_at=_NOW - timedelta(days=1),
    )


def _compiled_query(session: AsyncMock) -> tuple[str, dict[str, object]]:
    statement = session.scalar.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    return str(compiled), compiled.params


def test_get_returns_profile_for_user_scoped_query() -> None:
    user_id = uuid4()
    expected = _profile(user_id)
    session = _session()
    session.scalar.return_value = expected

    result = asyncio.run(
        FinancialProfileRepository().get_by_user_id(
            session,
            user_id=user_id,
        )
    )

    query, params = _compiled_query(session)
    assert result is expected
    assert "financial_profiles.user_id =" in query
    assert user_id in params.values()
    assert "FOR UPDATE" not in query


def test_get_returns_none_when_user_has_no_profile() -> None:
    session = _session()
    session.scalar.return_value = None

    result = asyncio.run(
        FinancialProfileRepository().get_by_user_id(
            session,
            user_id=uuid4(),
        )
    )

    assert result is None


def test_get_can_lock_the_user_scoped_profile() -> None:
    user_id = uuid4()
    session = _session()
    session.scalar.return_value = _profile(user_id)

    asyncio.run(
        FinancialProfileRepository().get_by_user_id(
            session,
            user_id=user_id,
            for_update=True,
        )
    )

    query, params = _compiled_query(session)
    assert "financial_profiles.user_id =" in query
    assert user_id in params.values()
    assert "FOR UPDATE" in query


def test_create_adds_complete_user_owned_profile() -> None:
    user_id = uuid4()
    session = _session()
    values = _values()

    profile = asyncio.run(
        FinancialProfileRepository().create(
            session,
            user_id=user_id,
            values=values,
            now=_NOW,
        )
    )

    assert profile.id is not None
    assert profile.user_id == user_id
    assert profile.income_pattern is IncomePattern.SALARIED
    assert profile.income_stability is IncomeStability.STABLE
    assert profile.has_household_responsibilities is True
    assert profile.dependant_count == 2
    assert profile.emergency_fund_target_months == Decimal("6.00")
    assert profile.completion_status is ProfileCompletionStatus.COMPLETE
    assert profile.created_at == _NOW
    assert profile.updated_at == _NOW
    session.add.assert_called_once_with(profile)
    session.flush.assert_awaited_once_with()


def test_create_preserves_draft_status_from_application_layer() -> None:
    session = _session()
    values = FinancialProfileValues(
        income_pattern=None,
        income_stability=None,
        has_household_responsibilities=False,
        dependant_count=0,
        emergency_fund_target_months=None,
        completion_status=ProfileCompletionStatus.DRAFT,
    )

    profile = asyncio.run(
        FinancialProfileRepository().create(
            session,
            user_id=uuid4(),
            values=values,
            now=_NOW,
        )
    )

    assert profile.income_pattern is None
    assert profile.income_stability is None
    assert profile.completion_status is ProfileCompletionStatus.DRAFT


def test_replace_updates_mutable_values_and_preserves_identity() -> None:
    user_id = uuid4()
    session = _session()
    profile = _profile(user_id)
    profile_id = profile.id
    created_at = profile.created_at

    result = asyncio.run(
        FinancialProfileRepository().replace(
            session,
            user_id=user_id,
            profile=profile,
            values=_values(),
            now=_NOW,
        )
    )

    assert result is profile
    assert profile.id == profile_id
    assert profile.user_id == user_id
    assert profile.created_at == created_at
    assert profile.updated_at == _NOW
    assert profile.income_pattern is IncomePattern.SALARIED
    assert profile.income_stability is IncomeStability.STABLE
    assert profile.has_household_responsibilities is True
    assert profile.dependant_count == 2
    assert profile.emergency_fund_target_months == Decimal("6.00")
    assert profile.completion_status is ProfileCompletionStatus.COMPLETE
    session.add.assert_not_called()
    session.flush.assert_awaited_once_with()


def test_replace_rejects_cross_user_profile() -> None:
    session = _session()
    profile = _profile(uuid4())

    with pytest.raises(
        ValueError,
        match="does not belong to the specified user",
    ):
        asyncio.run(
            FinancialProfileRepository().replace(
                session,
                user_id=uuid4(),
                profile=profile,
                values=_values(),
                now=_NOW,
            )
        )

    session.flush.assert_not_awaited()


def test_repository_never_commits_transaction() -> None:
    user_id = uuid4()
    session = _session()

    asyncio.run(
        FinancialProfileRepository().create(
            session,
            user_id=user_id,
            values=_values(),
            now=_NOW,
        )
    )

    session.commit.assert_not_awaited()
