"""Harden cross-table domain integrity.

Revision ID: a1b1833784e5
Revises: 771fa3a74464
"""

from collections.abc import Sequence

from alembic import op


revision: str = "a1b1833784e5"
down_revision: str | Sequence[str] | None = "771fa3a74464"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add cross-table category, liability and allocation enforcement."""
    op.execute(
        """
        CREATE FUNCTION falcon_assert_category_reference(
            checked_category_id uuid,
            checked_user_id uuid,
            required_kind varchar
        )
        RETURNS void
        LANGUAGE plpgsql
        AS $$
        DECLARE
            category_user_id uuid;
            category_is_system boolean;
            category_kind varchar;
        BEGIN
            IF checked_category_id IS NULL THEN
                RETURN;
            END IF;

            SELECT user_id, is_system, kind
            INTO
                category_user_id,
                category_is_system,
                category_kind
            FROM categories
            WHERE id = checked_category_id;

            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'The referenced category does not exist.'
                    USING ERRCODE = '23503';
            END IF;

            IF (
                NOT category_is_system
                AND category_user_id IS DISTINCT FROM checked_user_id
            ) THEN
                RAISE EXCEPTION
                    'Custom category ownership must match.'
                    USING ERRCODE = '23514';
            END IF;

            IF (
                required_kind IS NOT NULL
                AND category_kind <> required_kind
            ) THEN
                RAISE EXCEPTION
                    'Category kind % is incompatible with required kind %.',
                    category_kind,
                    required_kind
                    USING ERRCODE = '23514';
            END IF;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE FUNCTION falcon_validate_transaction_category()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            required_kind varchar;
        BEGIN
            required_kind := CASE NEW.transaction_type
                WHEN 'income' THEN 'income'
                WHEN 'expense' THEN 'expense'
                WHEN 'transfer' THEN 'transfer'
                ELSE NULL
            END;

            PERFORM falcon_assert_category_reference(
                NEW.category_id,
                NEW.user_id,
                required_kind
            );

            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_transactions_validate_category
        BEFORE INSERT OR UPDATE OF
            user_id,
            category_id,
            transaction_type
        ON transactions
        FOR EACH ROW
        EXECUTE FUNCTION falcon_validate_transaction_category();
        """
    )
    op.execute(
        """
        CREATE FUNCTION falcon_validate_budget_limit_category()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            PERFORM falcon_assert_category_reference(
                NEW.category_id,
                NEW.user_id,
                'expense'
            );

            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_budget_limits_validate_category
        BEFORE INSERT OR UPDATE OF
            user_id,
            category_id
        ON budget_limits
        FOR EACH ROW
        EXECUTE FUNCTION falcon_validate_budget_limit_category();
        """
    )
    op.execute(
        """
        CREATE FUNCTION falcon_validate_category_dependents()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF (
                NOT NEW.is_system
                AND EXISTS (
                    SELECT 1
                    FROM transactions
                    WHERE category_id = NEW.id
                    AND user_id IS DISTINCT FROM NEW.user_id
                )
            ) THEN
                RAISE EXCEPTION
                    'Category ownership change would invalidate transactions.'
                    USING ERRCODE = '23514';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM transactions
                WHERE category_id = NEW.id
                AND (
                    (transaction_type = 'income' AND NEW.kind <> 'income')
                    OR (
                        transaction_type = 'expense'
                        AND NEW.kind <> 'expense'
                    )
                    OR (
                        transaction_type = 'transfer'
                        AND NEW.kind <> 'transfer'
                    )
                )
            ) THEN
                RAISE EXCEPTION
                    'Category kind change would invalidate transactions.'
                    USING ERRCODE = '23514';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM budget_limits
                WHERE category_id = NEW.id
                AND (
                    NEW.kind <> 'expense'
                    OR (
                        NOT NEW.is_system
                        AND user_id IS DISTINCT FROM NEW.user_id
                    )
                )
            ) THEN
                RAISE EXCEPTION
                    'Category change would invalidate budget limits.'
                    USING ERRCODE = '23514';
            END IF;

            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_categories_validate_dependents
        BEFORE UPDATE OF
            user_id,
            is_system,
            kind
        ON categories
        FOR EACH ROW
        EXECUTE FUNCTION falcon_validate_category_dependents();
        """
    )
    op.execute(
        """
        CREATE FUNCTION falcon_validate_liability_detail()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            related_account_type varchar;
        BEGIN
            SELECT account_type
            INTO related_account_type
            FROM accounts
            WHERE id = NEW.account_id
            AND user_id = NEW.user_id;

            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'The liability account does not exist for this user.'
                    USING ERRCODE = '23503';
            END IF;

            IF related_account_type NOT IN ('loan', 'credit_card') THEN
                RAISE EXCEPTION
                    'Liability details require a debt-bearing account.'
                    USING ERRCODE = '23514';
            END IF;

            IF related_account_type <> NEW.liability_subtype THEN
                RAISE EXCEPTION
                    'Liability subtype must match the account type.'
                    USING ERRCODE = '23514';
            END IF;

            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_liability_details_validate_account
        BEFORE INSERT OR UPDATE OF
            user_id,
            account_id,
            liability_subtype
        ON liability_details
        FOR EACH ROW
        EXECUTE FUNCTION falcon_validate_liability_detail();
        """
    )
    op.execute(
        """
        CREATE FUNCTION falcon_validate_account_liability()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM liability_details
                WHERE account_id = NEW.id
                AND (
                    NEW.account_type NOT IN ('loan', 'credit_card')
                    OR liability_subtype <> NEW.account_type
                )
            ) THEN
                RAISE EXCEPTION
                    'Account type change would invalidate liability details.'
                    USING ERRCODE = '23514';
            END IF;

            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_accounts_validate_liability
        BEFORE UPDATE OF account_type
        ON accounts
        FOR EACH ROW
        EXECUTE FUNCTION falcon_validate_account_liability();
        """
    )
    op.execute(
        """
        CREATE FUNCTION falcon_assert_transaction_allocation_valid(
            checked_transaction_id uuid
        )
        RETURNS void
        LANGUAGE plpgsql
        AS $$
        DECLARE
            eligible_amount numeric;
            allocated_amount numeric;
        BEGIN
            IF checked_transaction_id IS NULL THEN
                RETURN;
            END IF;

            SELECT abs(amount)
            INTO eligible_amount
            FROM transactions
            WHERE id = checked_transaction_id;

            IF NOT FOUND THEN
                RETURN;
            END IF;

            SELECT coalesce(sum(amount), 0)
            INTO allocated_amount
            FROM goal_contributions
            WHERE transaction_id = checked_transaction_id;

            IF allocated_amount > eligible_amount THEN
                RAISE EXCEPTION
                    'Goal allocations % exceed transaction amount %.',
                    allocated_amount,
                    eligible_amount
                    USING ERRCODE = '23514';
            END IF;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE FUNCTION falcon_enforce_transaction_allocation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_TABLE_NAME = 'transactions' THEN
                PERFORM falcon_assert_transaction_allocation_valid(NEW.id);
                RETURN NULL;
            END IF;

            IF TG_OP <> 'INSERT' AND OLD.transaction_id IS NOT NULL THEN
                PERFORM falcon_assert_transaction_allocation_valid(
                    OLD.transaction_id
                );
            END IF;

            IF (
                TG_OP <> 'DELETE'
                AND NEW.transaction_id IS NOT NULL
                AND (
                    TG_OP = 'INSERT'
                    OR NEW.transaction_id
                        IS DISTINCT FROM OLD.transaction_id
                )
            ) THEN
                PERFORM falcon_assert_transaction_allocation_valid(
                    NEW.transaction_id
                );
            END IF;

            RETURN NULL;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER
            trg_goal_contributions_allocation_integrity
        AFTER INSERT OR UPDATE OR DELETE
        ON goal_contributions
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION falcon_enforce_transaction_allocation();
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER
            trg_transactions_allocation_integrity
        AFTER UPDATE
        ON transactions
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION falcon_enforce_transaction_allocation();
        """
    )


def downgrade() -> None:
    """Remove Phase 2.6 cross-table integrity enforcement."""
    op.execute(
        """
        DROP TRIGGER IF EXISTS
            trg_transactions_allocation_integrity
        ON transactions;
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS
            trg_goal_contributions_allocation_integrity
        ON goal_contributions;
        """
    )
    op.execute(
        """
        DROP FUNCTION IF EXISTS falcon_enforce_transaction_allocation();
        """
    )
    op.execute(
        """
        DROP FUNCTION IF EXISTS
            falcon_assert_transaction_allocation_valid(uuid);
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS
            trg_accounts_validate_liability
        ON accounts;
        """
    )
    op.execute(
        """
        DROP FUNCTION IF EXISTS falcon_validate_account_liability();
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS
            trg_liability_details_validate_account
        ON liability_details;
        """
    )
    op.execute(
        """
        DROP FUNCTION IF EXISTS falcon_validate_liability_detail();
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS
            trg_categories_validate_dependents
        ON categories;
        """
    )
    op.execute(
        """
        DROP FUNCTION IF EXISTS falcon_validate_category_dependents();
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS
            trg_budget_limits_validate_category
        ON budget_limits;
        """
    )
    op.execute(
        """
        DROP FUNCTION IF EXISTS falcon_validate_budget_limit_category();
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS
            trg_transactions_validate_category
        ON transactions;
        """
    )
    op.execute(
        """
        DROP FUNCTION IF EXISTS falcon_validate_transaction_category();
        """
    )
    op.execute(
        """
        DROP FUNCTION IF EXISTS
            falcon_assert_category_reference(uuid, uuid, varchar);
        """
    )
