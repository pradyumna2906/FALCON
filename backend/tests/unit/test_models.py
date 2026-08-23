"""Domain-model metadata, type, constraint and index tests."""

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, Numeric
from sqlalchemy.orm import configure_mappers

from falcon_api.infrastructure.persistence import (
    MONEY_PRECISION,
    MONEY_SCALE,
    RATE_PRECISION,
    RATE_SCALE,
    Base,
)
from falcon_api.models import (
    Account,
    Budget,
    BudgetLimit,
    Category,
    FinancialProfile,
    Goal,
    GoalContribution,
    ImportJob,
    ImportJobIssue,
    LiabilityDetail,
    Transaction,
    TransactionClassification,
    TransferGroup,
    User,
    register_models,
)
from falcon_api.models.enums import (
    AccountType,
    CategoryKind,
    GoalStatus,
    TransactionType,
    enum_sql_values,
)


_EXPECTED_TABLES = {
    "accounts",
    "authentication_challenges",
    "authentication_delivery_outbox",
    "budget_limits",
    "budgets",
    "categories",
    "financial_profiles",
    "goal_contributions",
    "goals",
    "import_jobs",
    "import_job_issues",
    "liability_details",
    "refresh_sessions",
    "refresh_tokens",
    "transactions",
    "transaction_classifications",
    "transfer_groups",
    "user_credentials",
    "users",
}


def check_names(table_name: str) -> set[str]:
    """Return every named check constraint for one table."""
    table = Base.metadata.tables[table_name]
    return {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
        and constraint.name is not None
    }


def foreign_key_names(table_name: str) -> set[str]:
    """Return every named foreign-key constraint for one table."""
    table = Base.metadata.tables[table_name]
    return {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        and constraint.name is not None
    }


def index_names(table_name: str) -> set[str]:
    """Return every explicitly defined index for one table."""
    table = Base.metadata.tables[table_name]
    return {
        index.name
        for index in table.indexes
        if isinstance(index, Index)
        and index.name is not None
    }


def test_all_approved_domain_tables_are_registered() -> None:
    register_models()
    configure_mappers()

    assert set(Base.metadata.tables) == _EXPECTED_TABLES


def test_every_domain_table_uses_uuid_and_utc_audit_columns() -> None:
    for table_name in _EXPECTED_TABLES:
        table = Base.metadata.tables[table_name]

        assert table.c.id.primary_key is True
        assert table.c.id.nullable is False
        assert table.c.id.default is not None
        assert table.c.created_at.nullable is False
        assert table.c.created_at.type.timezone is True
        assert table.c.updated_at.nullable is False
        assert table.c.updated_at.type.timezone is True


def test_money_and_rate_columns_use_approved_precision() -> None:
    money_columns = [
        Account.__table__.c.opening_balance,
        LiabilityDetail.__table__.c.principal_amount,
        LiabilityDetail.__table__.c.outstanding_amount,
        LiabilityDetail.__table__.c.minimum_payment,
        Transaction.__table__.c.amount,
        Budget.__table__.c.overall_limit,
        BudgetLimit.__table__.c.limit_amount,
        Goal.__table__.c.target_amount,
        Goal.__table__.c.starting_amount,
        GoalContribution.__table__.c.amount,
    ]

    for column in money_columns:
        assert isinstance(column.type, Numeric)
        assert column.type.precision == MONEY_PRECISION
        assert column.type.scale == MONEY_SCALE
        assert column.type.asdecimal is True

    rate_column = LiabilityDetail.__table__.c.annual_interest_rate

    assert isinstance(rate_column.type, Numeric)
    assert rate_column.type.precision == RATE_PRECISION
    assert rate_column.type.scale == RATE_SCALE
    assert rate_column.type.asdecimal is True


def test_currency_and_calendar_columns_use_explicit_types() -> None:
    currency_columns = [
        User.__table__.c.default_currency,
        Account.__table__.c.currency,
        Budget.__table__.c.currency,
        Goal.__table__.c.currency,
    ]

    for column in currency_columns:
        assert column.type.length == 3

    assert Account.__table__.c.opening_balance_date.type.python_type is not None
    assert Transaction.__table__.c.transaction_date.type.python_type is not None
    assert Budget.__table__.c.period_start_date.type.python_type is not None
    assert Goal.__table__.c.target_date.type.python_type is not None


def test_controlled_value_checks_are_present() -> None:
    assert "ck_accounts_account_type_allowed" in check_names("accounts")
    assert "ck_categories_kind_allowed" in check_names("categories")
    assert (
        "ck_transactions_transaction_type_allowed"
        in check_names("transactions")
    )
    assert "ck_goals_status_allowed" in check_names("goals")
    assert (
        "ck_import_jobs_lifecycle_consistent"
        in check_names("import_jobs")
    )
    assert (
        "ck_import_jobs_reconciliation_consistent"
        in check_names("import_jobs")
    )
    assert "ck_import_jobs_adapter_matches_source" in check_names("import_jobs")
    assert (
        "ck_import_jobs_balance_reconciliation_matches_source"
        in check_names("import_jobs")
    )
    assert (
        "ck_transaction_classifications_decision_target_consistent"
        in check_names("transaction_classifications")
    )
    assert (
        "ck_transaction_classifications_reason_codes_allowed"
        in check_names("transaction_classifications")
    )

    assert "'bank'" in enum_sql_values(AccountType)
    assert "'expense'" in enum_sql_values(CategoryKind)
    assert "'transfer'" in enum_sql_values(TransactionType)
    assert "'completed'" in enum_sql_values(GoalStatus)


def test_composite_ownership_foreign_keys_are_present() -> None:
    assert (
        "fk_import_jobs_owner_account"
        in foreign_key_names("import_jobs")
    )
    assert (
        "fk_import_job_issues_owner_job"
        in foreign_key_names("import_job_issues")
    )
    assert (
        "fk_liability_details_owner_account"
        in foreign_key_names("liability_details")
    )
    assert (
        "fk_transactions_owner_account"
        in foreign_key_names("transactions")
    )
    assert (
        "fk_transactions_owner_import_job"
        in foreign_key_names("transactions")
    )
    assert (
        "fk_transactions_owner_transfer_group"
        in foreign_key_names("transactions")
    )
    assert (
        "fk_budget_limits_owner_budget"
        in foreign_key_names("budget_limits")
    )
    assert (
        "fk_goal_contributions_owner_goal"
        in foreign_key_names("goal_contributions")
    )
    assert (
        "fk_goal_contributions_owner_transaction"
        in foreign_key_names("goal_contributions")
    )
    assert (
        "fk_transaction_classifications_owner_transaction"
        in foreign_key_names("transaction_classifications")
    )
    assert (
        "fk_transaction_classifications_taxonomy_category"
        in foreign_key_names("transaction_classifications")
    )


def test_query_driven_indexes_are_present() -> None:
    assert "ix_accounts_user_active" in index_names("accounts")
    assert "ix_transactions_user_date" in index_names("transactions")
    assert "ix_transactions_account_date" in index_names("transactions")
    assert "ix_transactions_category_date" in index_names("transactions")
    assert "ix_budgets_user_active_period" in index_names("budgets")
    assert "ix_goals_user_status_deadline" in index_names("goals")
    assert (
        "ix_import_job_issues_job_row"
        in index_names("import_job_issues")
    )
    assert (
        "ix_transaction_classifications_user_created"
        in index_names("transaction_classifications")
    )
    assert (
        "ix_transaction_classifications_user_decision"
        in index_names("transaction_classifications")
    )


def test_relationship_cardinalities_are_configured() -> None:
    assert User.financial_profile.property.uselist is False
    assert Account.liability_detail.property.uselist is False
    assert TransferGroup.transactions.property.uselist is True
    assert Budget.limits.property.uselist is True
    assert Goal.contributions.property.uselist is True


def test_unique_single_child_boundaries_are_present() -> None:
    assert FinancialProfile.__table__.c.user_id.unique is True
    assert ImportJob.__table__.c.file_fingerprint.nullable is False
    assert Category.__table__.c.is_system.nullable is False
    assert ImportJob.__table__.c.account_id.nullable is False
    assert ImportJob.__table__.c.adapter_name.type.length == 64
    assert ImportJob.__table__.c.balance_reconciled.nullable is True
    assert ImportJobIssue.__table__.c.message.type.length == 200
    assert Category.__table__.c.classification_code.nullable is True
    assert TransactionClassification.__table__.c.transaction_id.nullable is False
