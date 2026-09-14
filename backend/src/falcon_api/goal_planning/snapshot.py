"""Immutable owner-scoped evidence snapshots for goal-plan generation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from falcon_api.analytics.types import money
from falcon_api.auth.clock import Clock, SystemClock
from falcon_api.goal_planning.capacity import (
    SavingsCapacityPlan,
    bridge_savings_forecast,
)
from falcon_api.goal_planning.progress import GoalProgress, calculate_goal_progress
from falcon_api.goal_planning.semantics import (
    GOAL_PLANNING_CONTRACT_VERSION,
    normalize_goal_currency,
    trusted_local_date,
)
from falcon_api.models.account import Account, LiabilityDetail
from falcon_api.models.enums import (
    AccountType,
    GoalStatus,
    ProfileCompletionStatus,
    TransactionStatus,
)
from falcon_api.models.forecasting import ForecastRun
from falcon_api.models.ledger import Transaction
from falcon_api.models.planning import Budget, Goal, GoalContribution
from falcon_api.models.user import FinancialProfile


class PlanningSnapshotWarning(StrEnum):
    """Stable explanations for incomplete or excluded planning evidence."""

    NO_ACTIVE_GOALS = "no_active_goals"
    MIXED_CURRENCY_GOALS_EXCLUDED = "mixed_currency_goals_excluded"
    PROFILE_MISSING = "profile_missing"
    PROFILE_INCOMPLETE = "profile_incomplete"
    BUDGET_MISSING = "budget_missing"
    DEBT_PAYMENT_INCOMPLETE = "debt_payment_incomplete"
    SAVINGS_FORECAST_MISSING = "savings_forecast_missing"
    SAVINGS_FORECAST_PROVISIONAL = "savings_forecast_provisional"
    SAVINGS_FORECAST_UNUSABLE = "savings_forecast_unusable"


@dataclass(frozen=True, slots=True)
class PlanningProfileEvidence:
    completion_status: ProfileCompletionStatus
    income_stability: str | None
    emergency_fund_target_months: Decimal | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PlanningFinancialEvidence:
    liquid_balance: Decimal
    liability_account_count: int
    liability_payment_count: int
    outstanding_debt: Decimal
    monthly_debt_payment: Decimal
    source_last_updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class PlanningBudgetEvidence:
    active_budget_count: int
    budget_with_overall_limit_count: int
    total_overall_limit: Decimal
    source_last_updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class PlanningProvenance:
    goal_ids: tuple[UUID, ...]
    contribution_count: int
    forecast_run_id: UUID | None
    source_last_updated_at: datetime | None


@dataclass(frozen=True, slots=True)
class GoalPlanningSnapshot:
    """Frozen evidence consumed by later ranking and optimization policies."""

    snapshot_id: str
    contract_version: str
    cutoff_at: datetime
    local_date: date
    timezone: str
    currency: str
    goals: tuple[GoalProgress, ...]
    profile: PlanningProfileEvidence | None
    finances: PlanningFinancialEvidence
    budgets: PlanningBudgetEvidence
    savings_capacity: SavingsCapacityPlan | None
    warnings: tuple[PlanningSnapshotWarning, ...]
    provenance: PlanningProvenance


@dataclass(frozen=True, slots=True)
class PlanningEvidenceRows:
    goals: tuple[Goal, ...]
    contribution_totals: tuple[tuple[UUID, Decimal], ...]
    contribution_count: int
    excluded_currency_goal_count: int
    profile: PlanningProfileEvidence | None
    finances: PlanningFinancialEvidence
    budgets: PlanningBudgetEvidence
    forecast: ForecastRun | None


class PlanningEvidenceRepository:
    """Read every planning input with owner, currency, and cutoff predicates."""

    async def load(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        currency: str,
        cutoff_at: datetime,
        local_date: date,
    ) -> PlanningEvidenceRows:
        goals = await self._goals(
            session,
            user_id=user_id,
            currency=currency,
            cutoff_at=cutoff_at,
        )
        goal_ids = tuple(goal.id for goal in goals)
        totals, contribution_count = await self._contributions(
            session,
            user_id=user_id,
            goal_ids=goal_ids,
            cutoff_at=cutoff_at,
        )
        return PlanningEvidenceRows(
            goals=goals,
            contribution_totals=totals,
            contribution_count=contribution_count,
            excluded_currency_goal_count=await self._excluded_goal_count(
                session,
                user_id=user_id,
                currency=currency,
                cutoff_at=cutoff_at,
            ),
            profile=await self._profile(
                session,
                user_id=user_id,
                cutoff_at=cutoff_at,
            ),
            finances=await self._finances(
                session,
                user_id=user_id,
                currency=currency,
                cutoff_at=cutoff_at,
                local_date=local_date,
            ),
            budgets=await self._budgets(
                session,
                user_id=user_id,
                currency=currency,
                cutoff_at=cutoff_at,
                local_date=local_date,
            ),
            forecast=await self._forecast(
                session,
                user_id=user_id,
                currency=currency,
                cutoff_at=cutoff_at,
            ),
        )

    async def _goals(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        currency: str,
        cutoff_at: datetime,
    ) -> tuple[Goal, ...]:
        priority_order = case(
            (Goal.priority == "critical", 0),
            (Goal.priority == "high", 1),
            (Goal.priority == "medium", 2),
            else_=3,
        )
        rows = await session.scalars(
            select(Goal)
            .where(
                Goal.user_id == user_id,
                Goal.currency == currency,
                Goal.status == GoalStatus.ACTIVE,
                Goal.created_at <= cutoff_at,
                Goal.updated_at <= cutoff_at,
            )
            .order_by(priority_order, Goal.target_date.asc(), Goal.id.asc())
        )
        return tuple(rows.all())

    async def _contributions(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        goal_ids: tuple[UUID, ...],
        cutoff_at: datetime,
    ) -> tuple[tuple[tuple[UUID, Decimal], ...], int]:
        if not goal_ids:
            return (), 0
        rows = (
            await session.execute(
                select(
                    GoalContribution.goal_id,
                    func.sum(GoalContribution.amount).label("amount"),
                    func.count().label("count"),
                )
                .where(
                    GoalContribution.user_id == user_id,
                    GoalContribution.goal_id.in_(goal_ids),
                    GoalContribution.created_at <= cutoff_at,
                    GoalContribution.updated_at <= cutoff_at,
                )
                .group_by(GoalContribution.goal_id)
                .order_by(GoalContribution.goal_id.asc())
            )
        ).mappings().all()
        return (
            tuple((row["goal_id"], money(row["amount"])) for row in rows),
            sum(int(row["count"]) for row in rows),
        )

    async def _excluded_goal_count(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        currency: str,
        cutoff_at: datetime,
    ) -> int:
        statement = select(func.count()).select_from(Goal).where(
            Goal.user_id == user_id,
            Goal.currency != currency,
            Goal.status == GoalStatus.ACTIVE,
            Goal.created_at <= cutoff_at,
            Goal.updated_at <= cutoff_at,
        )
        return int(await session.scalar(statement) or 0)

    async def _profile(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        cutoff_at: datetime,
    ) -> PlanningProfileEvidence | None:
        profile = await session.scalar(
            select(FinancialProfile).where(
                FinancialProfile.user_id == user_id,
                FinancialProfile.created_at <= cutoff_at,
                FinancialProfile.updated_at <= cutoff_at,
            )
        )
        if profile is None:
            return None
        return PlanningProfileEvidence(
            completion_status=ProfileCompletionStatus(profile.completion_status),
            income_stability=(
                str(profile.income_stability)
                if profile.income_stability is not None
                else None
            ),
            emergency_fund_target_months=profile.emergency_fund_target_months,
            updated_at=profile.updated_at,
        )

    async def _finances(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        currency: str,
        cutoff_at: datetime,
        local_date: date,
    ) -> PlanningFinancialEvidence:
        balance_by_account = (
            select(
                Account.id.label("account_id"),
                (
                    Account.opening_balance
                    + func.coalesce(func.sum(Transaction.amount), 0)
                ).label("balance"),
            )
            .select_from(Account)
            .outerjoin(
                Transaction,
                and_(
                    Transaction.user_id == Account.user_id,
                    Transaction.account_id == Account.id,
                    Transaction.status == TransactionStatus.POSTED,
                    Transaction.transaction_date <= local_date,
                    Transaction.created_at <= cutoff_at,
                    Transaction.updated_at <= cutoff_at,
                ),
            )
            .where(
                Account.user_id == user_id,
                Account.currency == currency,
                Account.account_type.in_(
                    (AccountType.BANK, AccountType.CASH, AccountType.WALLET)
                ),
                Account.opening_balance_date <= local_date,
                Account.created_at <= cutoff_at,
                Account.updated_at <= cutoff_at,
                or_(Account.archived_at.is_(None), Account.archived_at > cutoff_at),
            )
            .group_by(Account.id, Account.opening_balance)
            .subquery()
        )
        liquid = await session.scalar(
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (
                                balance_by_account.c.balance > 0,
                                balance_by_account.c.balance,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                )
            ).select_from(balance_by_account)
        )
        liability_row = (
            await session.execute(
                select(
                    func.count(Account.id).label("account_count"),
                    func.count(LiabilityDetail.minimum_payment).label("payment_count"),
                    func.coalesce(
                        func.sum(LiabilityDetail.outstanding_amount), 0
                    ).label("outstanding"),
                    func.coalesce(
                        func.sum(LiabilityDetail.minimum_payment), 0
                    ).label("monthly_payment"),
                    func.max(Account.updated_at).label("account_updated"),
                    func.max(LiabilityDetail.updated_at).label("liability_updated"),
                )
                .select_from(Account)
                .outerjoin(
                    LiabilityDetail,
                    and_(
                        LiabilityDetail.user_id == Account.user_id,
                        LiabilityDetail.account_id == Account.id,
                        LiabilityDetail.created_at <= cutoff_at,
                        LiabilityDetail.updated_at <= cutoff_at,
                    ),
                )
                .where(
                    Account.user_id == user_id,
                    Account.currency == currency,
                    Account.account_type.in_(
                        (AccountType.CREDIT_CARD, AccountType.LOAN)
                    ),
                    Account.created_at <= cutoff_at,
                    Account.updated_at <= cutoff_at,
                    or_(Account.archived_at.is_(None), Account.archived_at > cutoff_at),
                )
            )
        ).mappings().one()
        transaction_updated = await session.scalar(
            select(func.max(Transaction.updated_at))
            .select_from(Transaction)
            .join(
                Account,
                and_(
                    Account.user_id == Transaction.user_id,
                    Account.id == Transaction.account_id,
                ),
            )
            .where(
                Transaction.user_id == user_id,
                Account.currency == currency,
                Transaction.created_at <= cutoff_at,
                Transaction.updated_at <= cutoff_at,
            )
        )
        account_updated = await session.scalar(
            select(func.max(Account.updated_at)).where(
                Account.user_id == user_id,
                Account.currency == currency,
                Account.created_at <= cutoff_at,
                Account.updated_at <= cutoff_at,
            )
        )
        timestamps = tuple(
            value
            for value in (
                account_updated,
                liability_row["account_updated"],
                liability_row["liability_updated"],
                transaction_updated,
            )
            if value is not None
        )
        return PlanningFinancialEvidence(
            liquid_balance=money(Decimal(liquid or 0)),
            liability_account_count=int(liability_row["account_count"]),
            liability_payment_count=int(liability_row["payment_count"]),
            outstanding_debt=money(Decimal(liability_row["outstanding"])),
            monthly_debt_payment=money(Decimal(liability_row["monthly_payment"])),
            source_last_updated_at=max(timestamps, default=None),
        )

    async def _budgets(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        currency: str,
        cutoff_at: datetime,
        local_date: date,
    ) -> PlanningBudgetEvidence:
        row = (
            await session.execute(
                select(
                    func.count(Budget.id).label("budget_count"),
                    func.count(Budget.overall_limit).label("limit_count"),
                    func.coalesce(func.sum(Budget.overall_limit), 0).label("limit"),
                    func.max(Budget.updated_at).label("updated_at"),
                ).where(
                    Budget.user_id == user_id,
                    Budget.currency == currency,
                    Budget.period_start_date <= local_date,
                    Budget.period_end_date >= local_date,
                    Budget.created_at <= cutoff_at,
                    Budget.updated_at <= cutoff_at,
                    or_(Budget.archived_at.is_(None), Budget.archived_at > cutoff_at),
                )
            )
        ).mappings().one()
        return PlanningBudgetEvidence(
            active_budget_count=int(row["budget_count"]),
            budget_with_overall_limit_count=int(row["limit_count"]),
            total_overall_limit=money(Decimal(row["limit"])),
            source_last_updated_at=row["updated_at"],
        )

    async def _forecast(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        currency: str,
        cutoff_at: datetime,
    ) -> ForecastRun | None:
        statement = (
            select(ForecastRun)
            .options(selectinload(ForecastRun.points))
            .where(
                ForecastRun.user_id == user_id,
                ForecastRun.currency == currency,
                ForecastRun.target == "savings_amount",
                ForecastRun.granularity == "month",
                ForecastRun.data_cutoff_at <= cutoff_at,
                ForecastRun.created_at <= cutoff_at,
                or_(
                    ForecastRun.source_last_updated_at.is_(None),
                    ForecastRun.source_last_updated_at <= ForecastRun.data_cutoff_at,
                ),
            )
            .order_by(
                ForecastRun.data_cutoff_at.desc(),
                ForecastRun.created_at.desc(),
                ForecastRun.id.desc(),
            )
            .limit(1)
        )
        return await session.scalar(statement)


class GoalPlanningSnapshotService:
    """Freeze planning evidence and bridge an eligible savings forecast."""

    def __init__(
        self,
        *,
        repository: PlanningEvidenceRepository | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._repository = repository or PlanningEvidenceRepository()
        self._clock = clock or SystemClock()

    async def build(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        currency: str,
        trusted_timezone: str,
    ) -> GoalPlanningSnapshot:
        cutoff_at = self._clock.now()
        normalized_currency = normalize_goal_currency(currency)
        local_date = trusted_local_date(
            instant=cutoff_at,
            timezone=trusted_timezone,
        )
        evidence = await self._repository.load(
            session,
            user_id=user_id,
            currency=normalized_currency,
            cutoff_at=cutoff_at,
            local_date=local_date,
        )
        totals = dict(evidence.contribution_totals)
        goals = tuple(
            calculate_goal_progress(
                goal=goal,
                contribution_amount=totals.get(goal.id, Decimal("0")),
                calculated_on=local_date,
            )
            for goal in evidence.goals
        )
        warnings = _warnings(evidence)
        capacity = None
        if evidence.forecast is not None:
            try:
                capacity = bridge_savings_forecast(
                    evidence.forecast,
                    as_of=local_date,
                )
            except ValueError:
                warnings.append(PlanningSnapshotWarning.SAVINGS_FORECAST_UNUSABLE)

        source_timestamps = tuple(
            value
            for value in (
                *(goal.updated_at for goal in evidence.goals),
                evidence.profile.updated_at if evidence.profile is not None else None,
                evidence.finances.source_last_updated_at,
                evidence.budgets.source_last_updated_at,
                evidence.forecast.created_at if evidence.forecast is not None else None,
            )
            if value is not None
        )
        provenance = PlanningProvenance(
            goal_ids=tuple(goal.id for goal in evidence.goals),
            contribution_count=evidence.contribution_count,
            forecast_run_id=(
                evidence.forecast.id if evidence.forecast is not None else None
            ),
            source_last_updated_at=max(source_timestamps, default=None),
        )
        return GoalPlanningSnapshot(
            snapshot_id=_snapshot_id(
                cutoff_at=cutoff_at,
                currency=normalized_currency,
                goals=goals,
                provenance=provenance,
            ),
            contract_version=GOAL_PLANNING_CONTRACT_VERSION,
            cutoff_at=cutoff_at,
            local_date=local_date,
            timezone=trusted_timezone,
            currency=normalized_currency,
            goals=goals,
            profile=evidence.profile,
            finances=evidence.finances,
            budgets=evidence.budgets,
            savings_capacity=capacity,
            warnings=tuple(sorted(set(warnings), key=str)),
            provenance=provenance,
        )


def _warnings(evidence: PlanningEvidenceRows) -> list[PlanningSnapshotWarning]:
    warnings: list[PlanningSnapshotWarning] = []
    if not evidence.goals:
        warnings.append(PlanningSnapshotWarning.NO_ACTIVE_GOALS)
    if evidence.excluded_currency_goal_count:
        warnings.append(PlanningSnapshotWarning.MIXED_CURRENCY_GOALS_EXCLUDED)
    if evidence.profile is None:
        warnings.append(PlanningSnapshotWarning.PROFILE_MISSING)
    elif evidence.profile.completion_status is not ProfileCompletionStatus.COMPLETE:
        warnings.append(PlanningSnapshotWarning.PROFILE_INCOMPLETE)
    if evidence.budgets.active_budget_count == 0:
        warnings.append(PlanningSnapshotWarning.BUDGET_MISSING)
    if (
        evidence.finances.liability_payment_count
        < evidence.finances.liability_account_count
    ):
        warnings.append(PlanningSnapshotWarning.DEBT_PAYMENT_INCOMPLETE)
    if evidence.forecast is None:
        warnings.append(PlanningSnapshotWarning.SAVINGS_FORECAST_MISSING)
    elif evidence.forecast.uncertainty_reliability == "provisional":
        warnings.append(PlanningSnapshotWarning.SAVINGS_FORECAST_PROVISIONAL)
    return warnings


def _snapshot_id(
    *,
    cutoff_at: datetime,
    currency: str,
    goals: tuple[GoalProgress, ...],
    provenance: PlanningProvenance,
) -> str:
    payload = {
        "contract_version": GOAL_PLANNING_CONTRACT_VERSION,
        "cutoff_at": cutoff_at.isoformat(),
        "currency": currency,
        "goals": [
            {
                "id": str(goal.goal_id),
                "current": str(goal.current_amount),
                "remaining": str(goal.remaining_amount),
            }
            for goal in goals
        ],
        "contribution_count": provenance.contribution_count,
        "forecast_run_id": (
            str(provenance.forecast_run_id)
            if provenance.forecast_run_id is not None
            else None
        ),
        "source_last_updated_at": (
            provenance.source_last_updated_at.isoformat()
            if provenance.source_last_updated_at is not None
            else None
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
