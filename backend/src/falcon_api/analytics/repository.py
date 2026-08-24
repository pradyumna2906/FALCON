"""Owner- and currency-scoped PostgreSQL financial aggregations."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, and_, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from falcon_api.analytics.periods import AnalyticsPeriod
from falcon_api.analytics.types import (
    MAX_ANALYTICS_DIMENSION_ROWS,
    AccountAggregate,
    AnalyticsGranularity,
    AnalyticsSummaryAggregate,
    BudgetCategoryLimitDefinition,
    BudgetCategorySpendingAggregate,
    BudgetDefinition,
    CashFlowBucketAggregate,
    CategoryAggregate,
    MerchantAggregate,
    RecurringTransactionRecord,
    SpendingSignalTransactionRecord,
    money,
)
from falcon_api.classification.types import ClassificationDecision
from falcon_api.models.account import Account
from falcon_api.models.category import Category
from falcon_api.models.classification import TransactionClassification
from falcon_api.models.enums import (
    AccountType,
    CategoryKind,
    TransactionStatus,
    TransactionType,
)
from falcon_api.models.ledger import Transaction
from falcon_api.models.planning import Budget, BudgetLimit


_CASH_FLOW_TYPES = (TransactionType.INCOME, TransactionType.EXPENSE)


class AnalyticsRepository:
    """Read exact aggregates without accepting an owner from public input."""

    async def get_summary(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        period: AnalyticsPeriod,
        currency: str,
    ) -> AnalyticsSummaryAggregate:
        """Return contract metrics and completeness counts in one statement."""
        normalized_currency = _currency(currency)
        in_period = _in_period(period)
        owned_account = _owned_account_join()
        selected_currency = Account.currency == normalized_currency
        posted = Transaction.status == TransactionStatus.POSTED
        eligible = and_(
            selected_currency,
            posted,
            Transaction.transaction_type.in_(_CASH_FLOW_TYPES),
        )
        valid_category = _valid_category(user_id=user_id)
        unresolved = and_(eligible, ~valid_category)

        transfer_groups = (
            select(
                Transaction.transfer_group_id.label("transfer_group_id"),
                func.max(func.abs(Transaction.amount)).label("amount"),
            )
            .join(Account, owned_account)
            .where(
                Transaction.user_id == user_id,
                *in_period,
                selected_currency,
                posted,
                Transaction.transaction_type == TransactionType.TRANSFER,
                Transaction.transfer_group_id.is_not(None),
                Transaction.amount < 0,
            )
            .group_by(Transaction.transfer_group_id)
            .subquery()
        )
        transfer_volume = (
            select(func.coalesce(func.sum(transfer_groups.c.amount), 0))
            .select_from(transfer_groups)
            .scalar_subquery()
        )

        statement = (
            select(
                _money_sum(
                    and_(
                        eligible,
                        Transaction.transaction_type == TransactionType.INCOME,
                    )
                ).label("gross_income"),
                _money_sum(
                    and_(
                        eligible,
                        Transaction.transaction_type == TransactionType.EXPENSE,
                    )
                ).label("total_expense"),
                transfer_volume.label("internal_transfer_volume"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    selected_currency,
                                    posted,
                                    Transaction.transaction_type
                                    == TransactionType.ADJUSTMENT,
                                ),
                                Transaction.amount,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("net_adjustment"),
                _count_if(eligible).label("eligible_transaction_count"),
                _count_if(and_(eligible, valid_category)).label(
                    "categorized_transaction_count"
                ),
                _count_if(
                    and_(
                        unresolved,
                        TransactionClassification.decision
                        == ClassificationDecision.SUGGESTED,
                    )
                ).label("suggested_transaction_count"),
                _count_if(
                    and_(
                        unresolved,
                        TransactionClassification.decision
                        == ClassificationDecision.ABSTAINED,
                    )
                ).label("abstained_transaction_count"),
                _count_if(
                    and_(
                        selected_currency,
                        Transaction.status == TransactionStatus.PENDING,
                        Transaction.transaction_type.in_(_CASH_FLOW_TYPES),
                    )
                ).label("pending_count"),
                _count_if(
                    and_(
                        selected_currency,
                        posted,
                        Transaction.transaction_type == TransactionType.TRANSFER,
                    )
                ).label("transfer_entry_count"),
                _count_if(
                    and_(
                        selected_currency,
                        posted,
                        Transaction.transaction_type
                        == TransactionType.ADJUSTMENT,
                    )
                ).label("adjustment_count"),
                _count_if(
                    and_(
                        Account.currency != normalized_currency,
                        posted,
                        Transaction.transaction_type.in_(_CASH_FLOW_TYPES),
                    )
                ).label("other_currency_count"),
                func.max(
                    case((eligible, Transaction.transaction_date), else_=None)
                ).label("latest_transaction_date"),
                func.max(
                    case((eligible, Transaction.updated_at), else_=None)
                ).label("source_last_updated_at"),
            )
            .select_from(Transaction)
            .join(Account, owned_account)
            .outerjoin(Category, Category.id == Transaction.category_id)
            .outerjoin(
                TransactionClassification,
                and_(
                    TransactionClassification.user_id == Transaction.user_id,
                    TransactionClassification.transaction_id == Transaction.id,
                ),
            )
            .where(Transaction.user_id == user_id, *in_period)
        )
        row = (await session.execute(statement)).mappings().one()
        return AnalyticsSummaryAggregate(
            gross_income=money(row["gross_income"]),
            total_expense=money(row["total_expense"]),
            internal_transfer_volume=money(row["internal_transfer_volume"]),
            net_adjustment=money(row["net_adjustment"]),
            eligible_transaction_count=row["eligible_transaction_count"],
            categorized_transaction_count=row["categorized_transaction_count"],
            suggested_transaction_count=row["suggested_transaction_count"],
            abstained_transaction_count=row["abstained_transaction_count"],
            pending_count=row["pending_count"],
            transfer_entry_count=row["transfer_entry_count"],
            adjustment_count=row["adjustment_count"],
            other_currency_count=row["other_currency_count"],
            latest_transaction_date=row["latest_transaction_date"],
            source_last_updated_at=row["source_last_updated_at"],
        )

    async def list_cash_flow_buckets(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        period: AnalyticsPeriod,
        currency: str,
        granularity: AnalyticsGranularity,
    ) -> tuple[CashFlowBucketAggregate, ...]:
        """Return observed daily or monthly external cash-flow buckets."""
        resolved_granularity = AnalyticsGranularity(granularity)
        bucket = Transaction.transaction_date
        if resolved_granularity is AnalyticsGranularity.MONTH:
            bucket = cast(
                func.date_trunc("month", Transaction.transaction_date),
                Date,
            )
        statement = (
            select(
                bucket.label("period_start"),
                _money_sum(
                    Transaction.transaction_type == TransactionType.INCOME
                ).label("gross_income"),
                _money_sum(
                    Transaction.transaction_type == TransactionType.EXPENSE
                ).label("total_expense"),
                func.count().label("transaction_count"),
            )
            .select_from(Transaction)
            .join(Account, _owned_account_join())
            .where(
                Transaction.user_id == user_id,
                *_in_period(period),
                Account.currency == _currency(currency),
                Transaction.status == TransactionStatus.POSTED,
                Transaction.transaction_type.in_(_CASH_FLOW_TYPES),
            )
            .group_by(bucket)
            .order_by(bucket.asc())
        )
        rows = (await session.execute(statement)).mappings().all()
        return tuple(
            CashFlowBucketAggregate(
                period_start=row["period_start"],
                gross_income=money(row["gross_income"]),
                total_expense=money(row["total_expense"]),
                transaction_count=row["transaction_count"],
            )
            for row in rows
        )

    async def list_category_aggregates(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        period: AnalyticsPeriod,
        currency: str,
        limit: int = MAX_ANALYTICS_DIMENSION_ROWS,
        transaction_type: TransactionType | None = None,
    ) -> tuple[CategoryAggregate, ...]:
        """Return bounded allocations to valid canonical ledger categories."""
        _dimension_limit(limit)
        amount = func.sum(func.abs(Transaction.amount))
        statement = (
            select(
                Category.id.label("category_id"),
                Category.parent_id.label("parent_category_id"),
                Category.name.label("name"),
                Category.classification_code.label("classification_code"),
                Category.kind.label("kind"),
                amount.label("amount"),
                func.count().label("transaction_count"),
            )
            .select_from(Transaction)
            .join(Account, _owned_account_join())
            .join(Category, Category.id == Transaction.category_id)
            .where(
                Transaction.user_id == user_id,
                *_in_period(period),
                Account.currency == _currency(currency),
                Transaction.status == TransactionStatus.POSTED,
                _cash_flow_type_filter(transaction_type),
                _valid_category(user_id=user_id),
            )
            .group_by(
                Category.id,
                Category.parent_id,
                Category.name,
                Category.classification_code,
                Category.kind,
            )
            .order_by(amount.desc(), Category.id.asc())
            .limit(limit)
        )
        rows = (await session.execute(statement)).mappings().all()
        return tuple(
            CategoryAggregate(
                category_id=row["category_id"],
                parent_category_id=row["parent_category_id"],
                name=row["name"],
                classification_code=row["classification_code"],
                kind=CategoryKind(row["kind"]),
                amount=money(row["amount"]),
                transaction_count=row["transaction_count"],
            )
            for row in rows
        )

    async def list_merchant_aggregates(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        period: AnalyticsPeriod,
        currency: str,
        limit: int = MAX_ANALYTICS_DIMENSION_ROWS,
        transaction_type: TransactionType | None = None,
    ) -> tuple[MerchantAggregate, ...]:
        """Return bounded case-insensitive merchant allocations."""
        _dimension_limit(limit)
        normalized = func.nullif(func.lower(func.trim(Transaction.merchant_name)), "")
        display = func.min(func.nullif(func.trim(Transaction.merchant_name), ""))
        income = _money_sum(
            Transaction.transaction_type == TransactionType.INCOME
        )
        expense = _money_sum(
            Transaction.transaction_type == TransactionType.EXPENSE
        )
        total = income + expense
        statement = (
            select(
                normalized.label("normalized_merchant"),
                display.label("display_name"),
                income.label("gross_income"),
                expense.label("total_expense"),
                func.count().label("transaction_count"),
                _count_if(
                    Transaction.transaction_type == TransactionType.INCOME
                ).label("income_transaction_count"),
                _count_if(
                    Transaction.transaction_type == TransactionType.EXPENSE
                ).label("expense_transaction_count"),
            )
            .select_from(Transaction)
            .join(Account, _owned_account_join())
            .where(
                Transaction.user_id == user_id,
                *_in_period(period),
                Account.currency == _currency(currency),
                Transaction.status == TransactionStatus.POSTED,
                _cash_flow_type_filter(transaction_type),
            )
            .group_by(normalized)
            .order_by(total.desc(), normalized.asc().nulls_last())
            .limit(limit)
        )
        rows = (await session.execute(statement)).mappings().all()
        return tuple(
            MerchantAggregate(
                normalized_merchant=row["normalized_merchant"],
                display_name=row["display_name"],
                gross_income=money(row["gross_income"]),
                total_expense=money(row["total_expense"]),
                transaction_count=row["transaction_count"],
                income_transaction_count=row["income_transaction_count"],
                expense_transaction_count=row["expense_transaction_count"],
            )
            for row in rows
        )

    async def list_account_aggregates(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        period: AnalyticsPeriod,
        currency: str,
        limit: int = MAX_ANALYTICS_DIMENSION_ROWS,
        transaction_type: TransactionType | None = None,
    ) -> tuple[AccountAggregate, ...]:
        """Return bounded external cash flow by owned historical account."""
        _dimension_limit(limit)
        income = _money_sum(
            Transaction.transaction_type == TransactionType.INCOME
        )
        expense = _money_sum(
            Transaction.transaction_type == TransactionType.EXPENSE
        )
        total = income + expense
        statement = (
            select(
                Account.id.label("account_id"),
                Account.name.label("name"),
                Account.account_type.label("account_type"),
                income.label("gross_income"),
                expense.label("total_expense"),
                func.count().label("transaction_count"),
                _count_if(
                    Transaction.transaction_type == TransactionType.INCOME
                ).label("income_transaction_count"),
                _count_if(
                    Transaction.transaction_type == TransactionType.EXPENSE
                ).label("expense_transaction_count"),
            )
            .select_from(Transaction)
            .join(Account, _owned_account_join())
            .where(
                Transaction.user_id == user_id,
                *_in_period(period),
                Account.currency == _currency(currency),
                Transaction.status == TransactionStatus.POSTED,
                _cash_flow_type_filter(transaction_type),
            )
            .group_by(
                Account.id,
                Account.name,
                Account.account_type,
            )
            .order_by(total.desc(), Account.id.asc())
            .limit(limit)
        )
        rows = (await session.execute(statement)).mappings().all()
        return tuple(
            AccountAggregate(
                account_id=row["account_id"],
                name=row["name"],
                account_type=AccountType(row["account_type"]),
                gross_income=money(row["gross_income"]),
                total_expense=money(row["total_expense"]),
                transaction_count=row["transaction_count"],
                income_transaction_count=row["income_transaction_count"],
                expense_transaction_count=row["expense_transaction_count"],
            )
            for row in rows
        )

    async def list_recurring_transactions(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        period: AnalyticsPeriod,
        currency: str,
    ) -> tuple[RecurringTransactionRecord, ...]:
        """Return bounded recurrence evidence in one owner-scoped statement."""
        normalized_merchant = func.nullif(
            func.lower(func.trim(Transaction.merchant_name)),
            "",
        )
        display_name = func.nullif(func.trim(Transaction.merchant_name), "")
        valid_category = _valid_category(user_id=user_id)
        classification_code = case(
            (valid_category, Category.classification_code),
            else_=None,
        )
        category_name = case((valid_category, Category.name), else_=None)
        statement = (
            select(
                Transaction.transaction_date.label("transaction_date"),
                Transaction.transaction_type.label("transaction_type"),
                func.abs(Transaction.amount).label("amount"),
                normalized_merchant.label("normalized_merchant"),
                display_name.label("display_name"),
                classification_code.label("classification_code"),
                category_name.label("category_name"),
            )
            .select_from(Transaction)
            .join(Account, _owned_account_join())
            .outerjoin(Category, Category.id == Transaction.category_id)
            .where(
                Transaction.user_id == user_id,
                *_in_period(period),
                Account.currency == _currency(currency),
                Transaction.status == TransactionStatus.POSTED,
                Transaction.transaction_type.in_(_CASH_FLOW_TYPES),
                or_(normalized_merchant.is_not(None), valid_category),
            )
            .order_by(Transaction.transaction_date.asc(), Transaction.id.asc())
        )
        rows = (await session.execute(statement)).mappings().all()
        return tuple(
            RecurringTransactionRecord(
                transaction_date=row["transaction_date"],
                transaction_type=TransactionType(row["transaction_type"]),
                amount=money(row["amount"]),
                normalized_merchant=row["normalized_merchant"],
                display_name=row["display_name"],
                classification_code=row["classification_code"],
                category_name=row["category_name"],
            )
            for row in rows
        )

    async def list_spending_signal_transactions(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        period: AnalyticsPeriod,
        currency: str,
    ) -> tuple[SpendingSignalTransactionRecord, ...]:
        """Return private posted-expense evidence in one scoped statement."""
        normalized_merchant = func.nullif(
            func.lower(func.trim(Transaction.merchant_name)),
            "",
        )
        display_name = func.nullif(func.trim(Transaction.merchant_name), "")
        valid_category = _valid_category(user_id=user_id)
        statement = (
            select(
                Transaction.transaction_date.label("transaction_date"),
                func.abs(Transaction.amount).label("amount"),
                normalized_merchant.label("normalized_merchant"),
                display_name.label("display_name"),
                case(
                    (valid_category, Category.classification_code),
                    else_=None,
                ).label("classification_code"),
                case((valid_category, Category.name), else_=None).label(
                    "category_name"
                ),
            )
            .select_from(Transaction)
            .join(Account, _owned_account_join())
            .outerjoin(Category, Category.id == Transaction.category_id)
            .where(
                Transaction.user_id == user_id,
                *_in_period(period),
                Account.currency == _currency(currency),
                Transaction.status == TransactionStatus.POSTED,
                Transaction.transaction_type == TransactionType.EXPENSE,
            )
            .order_by(Transaction.transaction_date.asc(), Transaction.id.asc())
        )
        rows = (await session.execute(statement)).mappings().all()
        return tuple(
            SpendingSignalTransactionRecord(
                transaction_date=row["transaction_date"],
                amount=money(row["amount"]),
                normalized_merchant=row["normalized_merchant"],
                display_name=row["display_name"],
                classification_code=row["classification_code"],
                category_name=row["category_name"],
            )
            for row in rows
        )

    async def get_budget_definition(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        budget_id: UUID,
    ) -> BudgetDefinition | None:
        """Load one owned budget and all valid category limits in one query."""
        statement = (
            select(
                Budget.id.label("budget_id"),
                Budget.name.label("budget_name"),
                Budget.period_start_date,
                Budget.period_end_date,
                Budget.currency,
                Budget.overall_limit,
                Budget.archived_at,
                BudgetLimit.id.label("budget_limit_id"),
                BudgetLimit.category_id,
                BudgetLimit.limit_amount,
                Category.name.label("category_name"),
                Category.classification_code,
                Category.kind.label("category_kind"),
                Category.user_id.label("category_user_id"),
                Category.is_system.label("category_is_system"),
            )
            .select_from(Budget)
            .outerjoin(
                BudgetLimit,
                and_(
                    BudgetLimit.user_id == Budget.user_id,
                    BudgetLimit.budget_id == Budget.id,
                ),
            )
            .outerjoin(Category, Category.id == BudgetLimit.category_id)
            .where(Budget.user_id == user_id, Budget.id == budget_id)
            .order_by(BudgetLimit.id.asc().nulls_last())
        )
        rows = (await session.execute(statement)).mappings().all()
        if not rows:
            return None
        limits = []
        for row in rows:
            if row["budget_limit_id"] is None:
                continue
            visible_category = (
                row["category_is_system"] is True
                and row["category_user_id"] is None
            ) or (
                row["category_is_system"] is False
                and row["category_user_id"] == user_id
            )
            if (
                row["category_id"] is None
                or row["category_name"] is None
                or row["category_kind"] != CategoryKind.EXPENSE
                or not visible_category
            ):
                raise ValueError("Budget limit category integrity is invalid.")
            limits.append(
                BudgetCategoryLimitDefinition(
                    category_id=row["category_id"],
                    name=row["category_name"],
                    classification_code=row["classification_code"],
                    limit_amount=money(row["limit_amount"]),
                )
            )
        first = rows[0]
        return BudgetDefinition(
            budget_id=first["budget_id"],
            name=first["budget_name"],
            period_start_date=first["period_start_date"],
            period_end_date=first["period_end_date"],
            currency=first["currency"],
            overall_limit=(
                money(first["overall_limit"])
                if first["overall_limit"] is not None
                else None
            ),
            archived_at=first["archived_at"],
            category_limits=tuple(limits),
        )

    async def list_budget_category_spending(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        budget_id: UUID,
        period: AnalyticsPeriod,
    ) -> tuple[BudgetCategorySpendingAggregate, ...]:
        """Aggregate every configured category without a query per limit."""
        eligible_transaction = and_(
            Transaction.user_id == user_id,
            Transaction.category_id == BudgetLimit.category_id,
            *_in_period(period),
            Transaction.status == TransactionStatus.POSTED,
            Transaction.transaction_type == TransactionType.EXPENSE,
        )
        owned_currency_account = and_(
            Account.user_id == Transaction.user_id,
            Account.id == Transaction.account_id,
            Account.currency == Budget.currency,
        )
        valid_account = Account.id.is_not(None)
        amount = func.coalesce(
            func.sum(
                case(
                    (valid_account, func.abs(Transaction.amount)),
                    else_=0,
                )
            ),
            0,
        )
        statement = (
            select(
                BudgetLimit.category_id,
                amount.label("amount"),
                _count_if(valid_account).label("transaction_count"),
            )
            .select_from(BudgetLimit)
            .join(
                Budget,
                and_(
                    Budget.user_id == BudgetLimit.user_id,
                    Budget.id == BudgetLimit.budget_id,
                ),
            )
            .join(Category, Category.id == BudgetLimit.category_id)
            .outerjoin(Transaction, eligible_transaction)
            .outerjoin(Account, owned_currency_account)
            .where(
                BudgetLimit.user_id == user_id,
                BudgetLimit.budget_id == budget_id,
                Budget.user_id == user_id,
                _valid_budget_category(user_id=user_id),
            )
            .group_by(BudgetLimit.category_id)
            .order_by(BudgetLimit.category_id.asc())
        )
        rows = (await session.execute(statement)).mappings().all()
        return tuple(
            BudgetCategorySpendingAggregate(
                category_id=row["category_id"],
                amount=money(row["amount"]),
                transaction_count=row["transaction_count"],
            )
            for row in rows
        )


def _owned_account_join() -> ColumnElement[bool]:
    return and_(
        Account.user_id == Transaction.user_id,
        Account.id == Transaction.account_id,
    )


def _in_period(
    period: AnalyticsPeriod,
) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    return (
        Transaction.transaction_date >= period.date_from,
        Transaction.transaction_date <= period.date_to,
    )


def _valid_category(*, user_id: UUID) -> ColumnElement[bool]:
    allowed_owner = or_(
        and_(Category.is_system.is_(True), Category.user_id.is_(None)),
        and_(Category.is_system.is_(False), Category.user_id == user_id),
    )
    return and_(
        Category.id.is_not(None),
        Category.kind == Transaction.transaction_type,
        allowed_owner,
    )


def _valid_budget_category(*, user_id: UUID) -> ColumnElement[bool]:
    allowed_owner = or_(
        and_(Category.is_system.is_(True), Category.user_id.is_(None)),
        and_(Category.is_system.is_(False), Category.user_id == user_id),
    )
    return and_(
        Category.id.is_not(None),
        Category.kind == CategoryKind.EXPENSE,
        allowed_owner,
    )


def _money_sum(predicate: ColumnElement[bool]) -> ColumnElement[Decimal]:
    return func.coalesce(
        func.sum(case((predicate, func.abs(Transaction.amount)), else_=0)),
        0,
    )


def _count_if(predicate: ColumnElement[bool]) -> ColumnElement[int]:
    return func.count().filter(predicate)


def _cash_flow_type_filter(
    transaction_type: TransactionType | None,
) -> ColumnElement[bool]:
    if transaction_type is None:
        return Transaction.transaction_type.in_(_CASH_FLOW_TYPES)
    if transaction_type not in _CASH_FLOW_TYPES:
        raise ValueError("Analytics dimensions support income or expense only.")
    return Transaction.transaction_type == transaction_type


def _currency(value: str) -> str:
    normalized = value.strip().upper()
    if len(normalized) != 3 or not all(
        "A" <= character <= "Z" for character in normalized
    ):
        raise ValueError("Analytics currency must be a three-letter code.")
    return normalized


def _dimension_limit(value: int) -> None:
    if type(value) is not int or not 1 <= value <= MAX_ANALYTICS_DIMENSION_ROWS:
        raise ValueError(
            "Analytics dimension limits must be between 1 and "
            f"{MAX_ANALYTICS_DIMENSION_ROWS}."
        )
