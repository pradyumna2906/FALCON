"""PostgreSQL integrity tests for the initial FALCON domain schema."""

import os
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from falcon_api.core.config import AppEnvironment, Settings
from psycopg.errors import CheckViolation, ForeignKeyViolation


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("FALCON_RUN_DATABASE_INTEGRATION") != "1",
        reason="Set FALCON_RUN_DATABASE_INTEGRATION=1 to enable these tests.",
    ),
]

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_ALEMBIC_CONFIG = _REPOSITORY_ROOT / "backend" / "alembic.ini"


def integration_settings() -> Settings:
    """Load the ignored root environment for PostgreSQL tests."""
    return Settings(
        _env_file=_REPOSITORY_ROOT / ".env",
        env=AppEnvironment.TEST,
        debug=False,
        docs_enabled=False,
        cors_allowed_origins=(),
    )


def connect_to_postgresql() -> psycopg.Connection:
    """Open one synchronous test connection to PostgreSQL."""
    settings = integration_settings()

    return psycopg.connect(
        host=settings.db_host,
        port=settings.db_port,
        dbname=settings.db_name,
        user=settings.db_user,
        password=settings.db_password.get_secret_value(),
        connect_timeout=settings.db_connect_timeout_seconds,
    )


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> Iterator[None]:
    """Run integrity tests only against the reviewed schema head."""
    config = Config(str(_ALEMBIC_CONFIG))
    command.upgrade(config, "head")

    try:
        yield
    finally:
        command.downgrade(config, "base")


def insert_user(
    connection: psycopg.Connection,
    *,
    email: str,
) -> UUID:
    """Insert a minimal valid user and return its identifier."""
    user_id = uuid4()

    connection.execute(
        """
        INSERT INTO users (
            id,
            email,
            status,
            timezone,
            default_currency,
            created_at,
            updated_at
        )
        VALUES (%s, %s, 'active', 'UTC', 'INR', now(), now())
        """,
        (user_id, email),
    )

    return user_id


def insert_account(
    connection: psycopg.Connection,
    *,
    user_id: UUID,
    name: str,
    currency: str = "INR",
    opening_balance: Decimal = Decimal("0"),
) -> UUID:
    """Insert a minimal valid bank account."""
    account_id = uuid4()

    connection.execute(
        """
        INSERT INTO accounts (
            id,
            user_id,
            name,
            account_type,
            currency,
            opening_balance,
            opening_balance_date,
            created_at,
            updated_at
        )
        VALUES (
            %s,
            %s,
            %s,
            'bank',
            %s,
            %s,
            %s,
            now(),
            now()
        )
        """,
        (
            account_id,
            user_id,
            name,
            currency,
            opening_balance,
            date(2026, 1, 1),
        ),
    )

    return account_id


def insert_category(
    connection: psycopg.Connection,
    *,
    user_id: UUID | None,
    name: str,
    kind: str,
    is_system: bool,
    parent_id: UUID | None = None,
) -> UUID:
    """Insert a category in a system or custom namespace."""
    category_id = uuid4()

    connection.execute(
        """
        INSERT INTO categories (
            id,
            user_id,
            name,
            normalized_name,
            kind,
            parent_id,
            is_system,
            display_order,
            created_at,
            updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, 0, now(), now())
        """,
        (
            category_id,
            user_id,
            name,
            name.casefold(),
            kind,
            parent_id,
            is_system,
        ),
    )

    return category_id


def insert_transaction(
    connection: psycopg.Connection,
    *,
    user_id: UUID,
    account_id: UUID,
    amount: Decimal,
    description: str,
    transaction_type: str = "expense",
    source_type: str = "manual",
    category_id: UUID | None = None,
    transfer_group_id: UUID | None = None,
) -> UUID:
    """Insert one transaction with explicit ledger semantics."""
    transaction_id = uuid4()

    connection.execute(
        """
        INSERT INTO transactions (
            id,
            user_id,
            account_id,
            category_id,
            transfer_group_id,
            transaction_type,
            amount,
            transaction_date,
            description,
            source_type,
            status,
            is_user_modified,
            created_at,
            updated_at
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            'posted',
            false,
            now(),
            now()
        )
        """,
        (
            transaction_id,
            user_id,
            account_id,
            category_id,
            transfer_group_id,
            transaction_type,
            amount,
            date(2026, 1, 15),
            description,
            source_type,
        ),
    )

    return transaction_id


def test_exact_decimal_round_trip_and_currency_constraint() -> None:
    """Preserve four decimal places and reject invalid currency codes."""
    with connect_to_postgresql() as connection:
        user_id = insert_user(
            connection,
            email=f"decimal-{uuid4().hex}@falcon.test",
        )
        account_id = insert_account(
            connection,
            user_id=user_id,
            name=f"Decimal {uuid4().hex}",
            opening_balance=Decimal("123.4567"),
        )
        connection.commit()

        stored_amount = connection.execute(
            """
            SELECT opening_balance
            FROM accounts
            WHERE id = %s
            """,
            (account_id,),
        ).fetchone()

        assert stored_amount is not None
        assert stored_amount[0] == Decimal("123.4567")

        with pytest.raises(CheckViolation):
            insert_account(
                connection,
                user_id=user_id,
                name=f"Invalid currency {uuid4().hex}",
                currency="inr",
            )
            connection.commit()

        connection.rollback()


def test_composite_account_ownership_rejects_cross_user_transaction() -> None:
    """Prevent a transaction from referencing another user's account."""
    with connect_to_postgresql() as connection:
        first_user_id = insert_user(
            connection,
            email=f"owner-a-{uuid4().hex}@falcon.test",
        )
        second_user_id = insert_user(
            connection,
            email=f"owner-b-{uuid4().hex}@falcon.test",
        )
        first_account_id = insert_account(
            connection,
            user_id=first_user_id,
            name=f"Owner account {uuid4().hex}",
        )
        connection.commit()

        with pytest.raises(ForeignKeyViolation):
            insert_transaction(
                connection,
                user_id=second_user_id,
                account_id=first_account_id,
                amount=Decimal("-10.0000"),
                description="Rejected cross-user transaction",
            )

        connection.rollback()


def test_category_parent_scope_rejects_cross_user_hierarchy() -> None:
    """Allow system parents while rejecting another user's custom parent."""
    with connect_to_postgresql() as connection:
        first_user_id = insert_user(
            connection,
            email=f"category-a-{uuid4().hex}@falcon.test",
        )
        second_user_id = insert_user(
            connection,
            email=f"category-b-{uuid4().hex}@falcon.test",
        )
        private_parent_id = insert_category(
            connection,
            user_id=first_user_id,
            name=f"Private parent {uuid4().hex}",
            kind="expense",
            is_system=False,
        )
        system_parent_id = insert_category(
            connection,
            user_id=None,
            name=f"System parent {uuid4().hex}",
            kind="expense",
            is_system=True,
        )
        connection.commit()

        insert_category(
            connection,
            user_id=second_user_id,
            name=f"Allowed child {uuid4().hex}",
            kind="expense",
            is_system=False,
            parent_id=system_parent_id,
        )
        connection.commit()

        with pytest.raises(CheckViolation):
            insert_category(
                connection,
                user_id=second_user_id,
                name=f"Rejected child {uuid4().hex}",
                kind="expense",
                is_system=False,
                parent_id=private_parent_id,
            )

        connection.rollback()


def test_deferred_transfer_integrity_accepts_pair_and_rejects_one_side() -> None:
    """Require two opposite same-currency entries on distinct accounts."""
    with connect_to_postgresql() as connection:
        user_id = insert_user(
            connection,
            email=f"transfer-{uuid4().hex}@falcon.test",
        )
        source_account_id = insert_account(
            connection,
            user_id=user_id,
            name=f"Transfer source {uuid4().hex}",
        )
        destination_account_id = insert_account(
            connection,
            user_id=user_id,
            name=f"Transfer destination {uuid4().hex}",
        )
        connection.commit()

        valid_group_id = uuid4()
        connection.execute(
            """
            INSERT INTO transfer_groups (
                id,
                user_id,
                created_at,
                updated_at
            )
            VALUES (%s, %s, now(), now())
            """,
            (valid_group_id, user_id),
        )
        insert_transaction(
            connection,
            user_id=user_id,
            account_id=source_account_id,
            amount=Decimal("-50.0000"),
            description="Transfer out",
            transaction_type="transfer",
            source_type="transfer",
            transfer_group_id=valid_group_id,
        )
        insert_transaction(
            connection,
            user_id=user_id,
            account_id=destination_account_id,
            amount=Decimal("50.0000"),
            description="Transfer in",
            transaction_type="transfer",
            source_type="transfer",
            transfer_group_id=valid_group_id,
        )
        connection.commit()

        entry_count = connection.execute(
            """
            SELECT count(*)
            FROM transactions
            WHERE transfer_group_id = %s
            """,
            (valid_group_id,),
        ).fetchone()

        assert entry_count == (2,)

        invalid_group_id = uuid4()
        connection.execute(
            """
            INSERT INTO transfer_groups (
                id,
                user_id,
                created_at,
                updated_at
            )
            VALUES (%s, %s, now(), now())
            """,
            (invalid_group_id, user_id),
        )
        insert_transaction(
            connection,
            user_id=user_id,
            account_id=source_account_id,
            amount=Decimal("-25.0000"),
            description="Incomplete transfer",
            transaction_type="transfer",
            source_type="transfer",
            transfer_group_id=invalid_group_id,
        )

        with pytest.raises(CheckViolation):
            connection.commit()

        connection.rollback()


def test_user_erasure_cascades_private_data_but_preserves_system_category() -> None:
    """Delete one user's private graph without deleting shared categories."""
    with connect_to_postgresql() as connection:
        user_id = insert_user(
            connection,
            email=f"erasure-{uuid4().hex}@falcon.test",
        )
        account_id = insert_account(
            connection,
            user_id=user_id,
            name=f"Erasure account {uuid4().hex}",
        )
        system_category_id = insert_category(
            connection,
            user_id=None,
            name=f"Shared category {uuid4().hex}",
            kind="expense",
            is_system=True,
        )
        private_category_id = insert_category(
            connection,
            user_id=user_id,
            name=f"Private category {uuid4().hex}",
            kind="expense",
            is_system=False,
        )
        insert_transaction(
            connection,
            user_id=user_id,
            account_id=account_id,
            category_id=private_category_id,
            amount=Decimal("-5.0000"),
            description="Private transaction",
        )
        connection.commit()

        connection.execute(
            "DELETE FROM users WHERE id = %s",
            (user_id,),
        )
        connection.commit()

        private_counts = connection.execute(
            """
            SELECT
                (SELECT count(*) FROM accounts WHERE user_id = %s),
                (SELECT count(*) FROM categories WHERE user_id = %s),
                (SELECT count(*) FROM transactions WHERE user_id = %s)
            """,
            (user_id, user_id, user_id),
        ).fetchone()

        assert private_counts == (0, 0, 0)

        system_count = connection.execute(
            """
            SELECT count(*)
            FROM categories
            WHERE id = %s
            """,
            (system_category_id,),
        ).fetchone()

        assert system_count == (1,)

def test_category_references_enforce_owner_kind_and_budget_eligibility() -> None:
    """Reject private cross-user, wrong-kind and ineligible budget categories."""
    with connect_to_postgresql() as connection:
        first_user_id = insert_user(
            connection,
            email=f"reference-a-{uuid4().hex}@falcon.test",
        )
        second_user_id = insert_user(
            connection,
            email=f"reference-b-{uuid4().hex}@falcon.test",
        )
        second_account_id = insert_account(
            connection,
            user_id=second_user_id,
            name=f"Reference account {uuid4().hex}",
        )
        private_expense_id = insert_category(
            connection,
            user_id=first_user_id,
            name=f"Private expense {uuid4().hex}",
            kind="expense",
            is_system=False,
        )
        system_income_id = insert_category(
            connection,
            user_id=None,
            name=f"System income {uuid4().hex}",
            kind="income",
            is_system=True,
        )
        connection.commit()

        with pytest.raises(CheckViolation):
            insert_transaction(
                connection,
                user_id=second_user_id,
                account_id=second_account_id,
                category_id=private_expense_id,
                amount=Decimal("-10.0000"),
                description="Rejected private category",
            )

        connection.rollback()

        with pytest.raises(CheckViolation):
            insert_transaction(
                connection,
                user_id=second_user_id,
                account_id=second_account_id,
                category_id=system_income_id,
                amount=Decimal("-10.0000"),
                description="Rejected category kind",
            )

        connection.rollback()

        budget_id = uuid4()
        connection.execute(
            """
            INSERT INTO budgets (
                id,
                user_id,
                name,
                period_start_date,
                period_end_date,
                currency,
                created_at,
                updated_at
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                'INR',
                now(),
                now()
            )
            """,
            (
                budget_id,
                second_user_id,
                f"Budget {uuid4().hex}",
                date(2026, 1, 1),
                date(2026, 1, 31),
            ),
        )
        connection.commit()

        with pytest.raises(CheckViolation):
            connection.execute(
                """
                INSERT INTO budget_limits (
                    id,
                    user_id,
                    budget_id,
                    category_id,
                    limit_amount,
                    created_at,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, now(), now())
                """,
                (
                    uuid4(),
                    second_user_id,
                    budget_id,
                    system_income_id,
                    Decimal("100.0000"),
                ),
            )

        connection.rollback()


def test_liability_details_require_matching_debt_account() -> None:
    """Reject non-debt accounts and account/subtype mismatches."""
    with connect_to_postgresql() as connection:
        user_id = insert_user(
            connection,
            email=f"liability-{uuid4().hex}@falcon.test",
        )
        bank_account_id = insert_account(
            connection,
            user_id=user_id,
            name=f"Bank account {uuid4().hex}",
        )
        loan_account_id = insert_account(
            connection,
            user_id=user_id,
            name=f"Loan account {uuid4().hex}",
        )
        connection.execute(
            """
            UPDATE accounts
            SET account_type = 'loan'
            WHERE id = %s
            """,
            (loan_account_id,),
        )
        connection.commit()

        with pytest.raises(CheckViolation):
            connection.execute(
                """
                INSERT INTO liability_details (
                    id,
                    user_id,
                    account_id,
                    liability_subtype,
                    created_at,
                    updated_at
                )
                VALUES (%s, %s, %s, 'loan', now(), now())
                """,
                (uuid4(), user_id, bank_account_id),
            )

        connection.rollback()

        liability_id = uuid4()
        connection.execute(
            """
            INSERT INTO liability_details (
                id,
                user_id,
                account_id,
                liability_subtype,
                principal_amount,
                annual_interest_rate,
                created_at,
                updated_at
            )
            VALUES (
                %s,
                %s,
                %s,
                'loan',
                %s,
                %s,
                now(),
                now()
            )
            """,
            (
                liability_id,
                user_id,
                loan_account_id,
                Decimal("100000.0000"),
                Decimal("0.075000"),
            ),
        )
        connection.commit()

        with pytest.raises(CheckViolation):
            connection.execute(
                """
                UPDATE accounts
                SET account_type = 'bank'
                WHERE id = %s
                """,
                (loan_account_id,),
            )

        connection.rollback()

        stored_values = connection.execute(
            """
            SELECT principal_amount, annual_interest_rate
            FROM liability_details
            WHERE id = %s
            """,
            (liability_id,),
        ).fetchone()

        assert stored_values == (
            Decimal("100000.0000"),
            Decimal("0.075000"),
        )


def test_goal_allocations_cannot_exceed_supporting_transaction() -> None:
    """Reject aggregate goal allocations above a transaction's magnitude."""
    with connect_to_postgresql() as connection:
        user_id = insert_user(
            connection,
            email=f"allocation-{uuid4().hex}@falcon.test",
        )
        account_id = insert_account(
            connection,
            user_id=user_id,
            name=f"Allocation account {uuid4().hex}",
        )
        transaction_id = insert_transaction(
            connection,
            user_id=user_id,
            account_id=account_id,
            amount=Decimal("-100.0000"),
            description="Eligible goal allocation",
        )
        goal_id = uuid4()

        connection.execute(
            """
            INSERT INTO goals (
                id,
                user_id,
                name,
                goal_type,
                target_amount,
                starting_amount,
                currency,
                target_date,
                priority,
                status,
                created_at,
                updated_at
            )
            VALUES (
                %s,
                %s,
                %s,
                'other',
                %s,
                %s,
                'INR',
                %s,
                'medium',
                'active',
                now(),
                now()
            )
            """,
            (
                goal_id,
                user_id,
                f"Allocation goal {uuid4().hex}",
                Decimal("1000.0000"),
                Decimal("0.0000"),
                date(2026, 12, 31),
            ),
        )
        connection.commit()

        connection.execute(
            """
            INSERT INTO goal_contributions (
                id,
                user_id,
                goal_id,
                transaction_id,
                amount,
                contribution_date,
                source_type,
                created_at,
                updated_at
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                'transaction',
                now(),
                now()
            )
            """,
            (
                uuid4(),
                user_id,
                goal_id,
                transaction_id,
                Decimal("60.0000"),
                date(2026, 1, 15),
            ),
        )
        connection.commit()

        connection.execute(
            """
            INSERT INTO goal_contributions (
                id,
                user_id,
                goal_id,
                transaction_id,
                amount,
                contribution_date,
                source_type,
                created_at,
                updated_at
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                'transaction',
                now(),
                now()
            )
            """,
            (
                uuid4(),
                user_id,
                goal_id,
                transaction_id,
                Decimal("50.0000"),
                date(2026, 1, 16),
            ),
        )

        with pytest.raises(CheckViolation):
            connection.commit()

        connection.rollback()

        allocated_amount = connection.execute(
            """
            SELECT sum(amount)
            FROM goal_contributions
            WHERE transaction_id = %s
            """,
            (transaction_id,),
        ).fetchone()

        assert allocated_amount == (Decimal("60.0000"),)


def test_expected_integrity_functions_and_triggers_exist() -> None:
    """Verify PostgreSQL contains the reviewed integrity objects."""
    expected_functions = {
        "falcon_assert_category_reference",
        "falcon_assert_transaction_allocation_valid",
        "falcon_assert_transfer_group_valid",
        "falcon_enforce_transaction_allocation",
        "falcon_enforce_transfer_integrity",
        "falcon_validate_account_liability",
        "falcon_validate_budget_limit_category",
        "falcon_validate_category_dependents",
        "falcon_validate_category_scope",
        "falcon_validate_liability_detail",
        "falcon_validate_transaction_category",
    }
    expected_triggers = {
        "trg_accounts_validate_liability",
        "trg_budget_limits_validate_category",
        "trg_categories_validate_dependents",
        "trg_categories_validate_scope",
        "trg_goal_contributions_allocation_integrity",
        "trg_liability_details_validate_account",
        "trg_transactions_allocation_integrity",
        "trg_transactions_transfer_integrity",
        "trg_transactions_validate_category",
        "trg_transfer_groups_pair_integrity",
    }

    with connect_to_postgresql() as connection:
        function_names = {
            row[0]
            for row in connection.execute(
                """
                SELECT proname
                FROM pg_proc
                WHERE proname LIKE 'falcon_%'
                """
            )
        }
        trigger_names = {
            row[0]
            for row in connection.execute(
                """
                SELECT tgname
                FROM pg_trigger
                WHERE NOT tgisinternal
                """
            )
        }

    assert expected_functions <= function_names
    assert expected_triggers <= trigger_names
