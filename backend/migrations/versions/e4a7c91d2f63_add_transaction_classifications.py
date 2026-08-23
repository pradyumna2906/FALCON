"""Add classification taxonomy categories and bounded prediction provenance.

Revision ID: e4a7c91d2f63
Revises: d8f3a2c7b419
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid5

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e4a7c91d2f63"
down_revision: str | Sequence[str] | None = "d8f3a2c7b419"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CATEGORY_NAMESPACE = UUID("6b2f44dc-850d-4d90-84ea-d19573b887d8")
_TAXONOMY_CATEGORIES = (
    ("groceries", "Groceries", "expense"),
    ("restaurants", "Restaurants", "expense"),
    ("food_delivery", "Food Delivery", "expense"),
    ("rent", "Rent", "expense"),
    ("home_maintenance", "Maintenance", "expense"),
    ("utilities", "Utilities", "expense"),
    ("fuel", "Fuel", "expense"),
    ("public_transport", "Public Transport", "expense"),
    ("taxi_ride_share", "Taxi & Ride Share", "expense"),
    ("vehicle_maintenance", "Vehicle Maintenance", "expense"),
    ("toll_parking", "Toll & Parking", "expense"),
    ("clothing", "Clothing", "expense"),
    ("electronics", "Electronics", "expense"),
    ("household_goods", "Household Goods", "expense"),
    ("general_shopping", "General Shopping", "expense"),
    ("pharmacy", "Pharmacy", "expense"),
    ("hospital_clinic", "Hospital & Clinic", "expense"),
    ("health_insurance", "Health Insurance", "expense"),
    ("tuition_fees", "Tuition & Fees", "expense"),
    ("courses", "Courses", "expense"),
    ("books_supplies", "Books & Supplies", "expense"),
    ("streaming", "Streaming", "expense"),
    ("movies_events", "Movies & Events", "expense"),
    ("gaming", "Gaming", "expense"),
    ("hobbies", "Hobbies", "expense"),
    ("emi_loan_payment", "EMI & Loan Payment", "expense"),
    ("bank_charges", "Bank Charges", "expense"),
    ("taxes", "Taxes", "expense"),
    ("other_insurance", "Other Insurance", "expense"),
    ("salary", "Salary", "income"),
    ("freelance", "Freelance", "income"),
    ("business_income", "Business Income", "income"),
    ("interest", "Interest", "income"),
    ("dividend", "Dividend", "income"),
    ("refund", "Refund", "income"),
    ("cashback", "Cashback", "income"),
    ("other_income", "Other Income", "income"),
    ("self_transfer", "Self Transfer", "transfer"),
    ("person_transfer", "Person Transfer", "transfer"),
    ("mutual_fund", "Mutual Fund", "expense"),
    ("stocks", "Stocks", "expense"),
    ("fixed_deposit", "Fixed Deposit", "expense"),
    ("retirement", "Retirement", "expense"),
    ("other_investment", "Other Investment", "expense"),
    ("atm_withdrawal", "ATM Withdrawal", "expense"),
    ("cash_deposit", "Cash Deposit", "income"),
    ("uncategorized", "Uncategorized", "expense"),
    ("other_expense", "Other Expense", "expense"),
)


def upgrade() -> None:
    """Install stable taxonomy mappings and classification provenance."""
    op.add_column(
        "categories",
        sa.Column("classification_code", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_categories_classification_code_system_only"),
        "categories",
        "classification_code IS NULL OR is_system",
    )
    op.create_check_constraint(
        op.f("ck_categories_classification_code_format"),
        "categories",
        (
            "classification_code IS NULL OR "
            "classification_code ~ '^[a-z][a-z0-9_]{0,63}$'"
        ),
    )
    op.create_unique_constraint(
        "uq_categories_id_classification_code",
        "categories",
        ["id", "classification_code"],
    )
    op.create_index(
        "uq_categories_classification_code",
        "categories",
        ["classification_code"],
        unique=True,
        postgresql_where=sa.text("classification_code IS NOT NULL"),
    )

    categories = sa.table(
        "categories",
        sa.column("id", sa.Uuid()),
        sa.column("user_id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("normalized_name", sa.String()),
        sa.column("classification_code", sa.String()),
        sa.column("kind", sa.String()),
        sa.column("parent_id", sa.Uuid()),
        sa.column("is_system", sa.Boolean()),
        sa.column("display_order", sa.Integer()),
        sa.column("archived_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(UTC)
    category_rows = [
        {
            "id": uuid5(_CATEGORY_NAMESPACE, code),
            "user_id": None,
            "name": name,
            "normalized_name": code,
            "classification_code": code,
            "kind": kind,
            "parent_id": None,
            "is_system": True,
            "display_order": order,
            "archived_at": None,
            "created_at": now,
            "updated_at": now,
        }
        for order, (code, name, kind) in enumerate(_TAXONOMY_CATEGORIES)
    ]
    category_insert = postgresql.insert(categories).values(category_rows)
    op.execute(
        category_insert.on_conflict_do_update(
            index_elements=[categories.c.id],
            set_={
                "name": category_insert.excluded.name,
                "normalized_name": category_insert.excluded.normalized_name,
                "classification_code": (
                    category_insert.excluded.classification_code
                ),
                "kind": category_insert.excluded.kind,
                "is_system": category_insert.excluded.is_system,
                "display_order": category_insert.excluded.display_order,
                "archived_at": None,
                "updated_at": category_insert.excluded.updated_at,
            },
        )
    )

    op.create_table(
        "transaction_classifications",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_category_id", sa.Uuid(), nullable=True),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("category_code", sa.String(length=64), nullable=True),
        sa.Column("subcategory_code", sa.String(length=64), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column(
            "reason_codes",
            postgresql.ARRAY(sa.String(length=64), dimensions=1),
            nullable=False,
        ),
        sa.Column("taxonomy_version", sa.String(length=64), nullable=False),
        sa.Column("ruleset_version", sa.String(length=64), nullable=True),
        sa.Column("model_version", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "category_code IS NULL OR category_code IN ("
            "'food_dining', 'housing', 'transportation', 'shopping', "
            "'healthcare', 'education', 'entertainment', 'financial', "
            "'income', 'transfer', 'investment', 'cash', 'other')",
            name=op.f("ck_transaction_classifications_category_code_allowed"),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("ck_transaction_classifications_confidence_bounded"),
        ),
        sa.CheckConstraint(
            "decision IN ('automatic', 'suggested', 'abstained')",
            name=op.f("ck_transaction_classifications_decision_allowed"),
        ),
        sa.CheckConstraint(
            "(decision = 'automatic' AND category_code IS NOT NULL "
            "AND subcategory_code IS NOT NULL "
            "AND assigned_category_id IS NOT NULL) OR "
            "(decision = 'suggested' AND category_code IS NOT NULL "
            "AND subcategory_code IS NOT NULL "
            "AND assigned_category_id IS NULL) OR "
            "(decision = 'abstained' AND category_code IS NULL "
            "AND subcategory_code IS NULL "
            "AND assigned_category_id IS NULL)",
            name=op.f(
                "ck_transaction_classifications_decision_target_consistent"
            ),
        ),
        sa.CheckConstraint(
            "model_version IS NULL OR length(trim(model_version)) > 0",
            name=op.f(
                "ck_transaction_classifications_model_version_not_blank"
            ),
        ),
        sa.CheckConstraint(
            "cardinality(reason_codes) BETWEEN 1 AND 5",
            name=op.f(
                "ck_transaction_classifications_reason_codes_bounded"
            ),
        ),
        sa.CheckConstraint(
            "reason_codes <@ ARRAY['known_merchant', 'keyword_rule', "
            "'user_merchant_memory', 'model_prediction', "
            "'rule_model_agreement', 'provisional_model', "
            "'classifier_unavailable', 'low_confidence', "
            "'ambiguous_prediction', "
            "'unsupported_transaction_type']::varchar[]",
            name=op.f(
                "ck_transaction_classifications_reason_codes_allowed"
            ),
        ),
        sa.CheckConstraint(
            "ruleset_version IS NULL OR length(trim(ruleset_version)) > 0",
            name=op.f(
                "ck_transaction_classifications_ruleset_version_not_blank"
            ),
        ),
        sa.CheckConstraint(
            "source IN ('rule', 'merchant_memory', 'ml', 'hybrid')",
            name=op.f("ck_transaction_classifications_source_allowed"),
        ),
        sa.CheckConstraint(
            "((source IN ('rule', 'hybrid')) = "
            "(ruleset_version IS NOT NULL)) AND "
            "((source IN ('ml', 'hybrid')) = (model_version IS NOT NULL))",
            name=op.f(
                "ck_transaction_classifications_source_version_consistent"
            ),
        ),
        sa.CheckConstraint(
            "subcategory_code IS NULL OR subcategory_code IN ("
            + ", ".join(f"'{code}'" for code, _, _ in _TAXONOMY_CATEGORIES)
            + ")",
            name=op.f(
                "ck_transaction_classifications_subcategory_code_allowed"
            ),
        ),
        sa.CheckConstraint(
            "length(trim(taxonomy_version)) > 0",
            name=op.f(
                "ck_transaction_classifications_taxonomy_version_not_blank"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["assigned_category_id", "subcategory_code"],
            ["categories.id", "categories.classification_code"],
            name="fk_transaction_classifications_taxonomy_category",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "transaction_id"],
            ["transactions.user_id", "transactions.id"],
            name="fk_transaction_classifications_owner_transaction",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_transaction_classifications_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_transaction_classifications")
        ),
        sa.UniqueConstraint(
            "user_id",
            "transaction_id",
            name="uq_transaction_classifications_owner_transaction",
        ),
    )
    op.create_index(
        "ix_transaction_classifications_user_created",
        "transaction_classifications",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_transaction_classifications_user_decision",
        "transaction_classifications",
        ["user_id", "decision"],
        unique=False,
    )


def downgrade() -> None:
    """Remove prediction provenance and seeded taxonomy mappings."""
    op.drop_index(
        "ix_transaction_classifications_user_decision",
        table_name="transaction_classifications",
    )
    op.drop_index(
        "ix_transaction_classifications_user_created",
        table_name="transaction_classifications",
    )
    op.drop_table("transaction_classifications")
    category_ids = tuple(
        uuid5(_CATEGORY_NAMESPACE, code)
        for code, _, _ in _TAXONOMY_CATEGORIES
    )
    categories = sa.table(
        "categories",
        sa.column("id", sa.Uuid()),
        sa.column("classification_code", sa.String()),
    )
    op.execute(
        categories.update()
        .where(categories.c.id.in_(category_ids))
        .values(classification_code=None)
    )
    op.drop_index(
        "uq_categories_classification_code", table_name="categories"
    )
    op.drop_constraint(
        "uq_categories_id_classification_code",
        "categories",
        type_="unique",
    )
    op.drop_constraint(
        op.f("ck_categories_classification_code_format"),
        "categories",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_categories_classification_code_system_only"),
        "categories",
        type_="check",
    )
    op.drop_column("categories", "classification_code")
