"""Add immutable classification corrections and personal merchant memory.

Revision ID: f7b2d4e8a901
Revises: e4a7c91d2f63
"""

from alembic import op
from collections.abc import Sequence
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f7b2d4e8a901"
down_revision: str | Sequence[str] | None = "e4a7c91d2f63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CATEGORY_CODES = (
    "food_dining",
    "housing",
    "transportation",
    "shopping",
    "healthcare",
    "education",
    "entertainment",
    "financial",
    "income",
    "transfer",
    "investment",
    "cash",
    "other",
)
_SUBCATEGORY_CODES = (
    "groceries",
    "restaurants",
    "food_delivery",
    "rent",
    "home_maintenance",
    "utilities",
    "fuel",
    "public_transport",
    "taxi_ride_share",
    "vehicle_maintenance",
    "toll_parking",
    "clothing",
    "electronics",
    "household_goods",
    "general_shopping",
    "pharmacy",
    "hospital_clinic",
    "health_insurance",
    "tuition_fees",
    "courses",
    "books_supplies",
    "streaming",
    "movies_events",
    "gaming",
    "hobbies",
    "emi_loan_payment",
    "bank_charges",
    "taxes",
    "other_insurance",
    "salary",
    "freelance",
    "business_income",
    "interest",
    "dividend",
    "refund",
    "cashback",
    "other_income",
    "self_transfer",
    "person_transfer",
    "mutual_fund",
    "stocks",
    "fixed_deposit",
    "retirement",
    "other_investment",
    "atm_withdrawal",
    "cash_deposit",
    "uncategorized",
    "other_expense",
)
_REASON_CODES = (
    "known_merchant",
    "keyword_rule",
    "user_merchant_memory",
    "model_prediction",
    "rule_model_agreement",
    "provisional_model",
    "classifier_unavailable",
    "low_confidence",
    "ambiguous_prediction",
    "unsupported_transaction_type",
)


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    """Install owner-isolated memory and append-only correction feedback."""
    op.create_unique_constraint(
        "uq_transaction_classifications_owner_transaction_id",
        "transaction_classifications",
        ["user_id", "transaction_id", "id"],
    )
    op.create_table(
        "user_merchant_memories",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("normalized_merchant", sa.String(length=200), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("category_code", sa.String(length=64), nullable=False),
        sa.Column("subcategory_code", sa.String(length=64), nullable=False),
        sa.Column("taxonomy_version", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"category_code IN ({_quoted(_CATEGORY_CODES)})",
            name=op.f("ck_user_merchant_memories_category_code_allowed"),
        ),
        sa.CheckConstraint(
            "length(trim(normalized_merchant)) BETWEEN 1 AND 200",
            name=op.f("ck_user_merchant_memories_normalized_merchant_bounded"),
        ),
        sa.CheckConstraint(
            "normalized_merchant = lower(normalized_merchant)",
            name=op.f("ck_user_merchant_memories_normalized_merchant_lowercase"),
        ),
        sa.CheckConstraint(
            f"subcategory_code IN ({_quoted(_SUBCATEGORY_CODES)})",
            name=op.f("ck_user_merchant_memories_subcategory_code_allowed"),
        ),
        sa.CheckConstraint(
            "length(trim(taxonomy_version)) > 0",
            name=op.f("ck_user_merchant_memories_taxonomy_version_not_blank"),
        ),
        sa.ForeignKeyConstraint(
            ["category_id", "subcategory_code"],
            ["categories.id", "categories.classification_code"],
            name="fk_user_merchant_memories_taxonomy_category",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_merchant_memories_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_merchant_memories")),
        sa.UniqueConstraint(
            "user_id",
            "normalized_merchant",
            name="uq_user_merchant_memories_owner_merchant",
        ),
        sa.UniqueConstraint(
            "user_id",
            "id",
            name="uq_user_merchant_memories_user_id_id",
        ),
    )
    op.create_index(
        "ix_user_merchant_memories_user_updated",
        "user_merchant_memories",
        ["user_id", "updated_at"],
        unique=False,
    )

    op.create_table(
        "transaction_category_corrections",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("classification_id", sa.Uuid(), nullable=False),
        sa.Column("original_decision", sa.String(length=16), nullable=False),
        sa.Column("original_source", sa.String(length=24), nullable=False),
        sa.Column("original_category_code", sa.String(length=64), nullable=True),
        sa.Column("original_subcategory_code", sa.String(length=64), nullable=True),
        sa.Column("original_confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column(
            "original_reason_codes",
            postgresql.ARRAY(sa.String(length=64), dimensions=1),
            nullable=False,
        ),
        sa.Column("original_taxonomy_version", sa.String(length=64), nullable=False),
        sa.Column("original_ruleset_version", sa.String(length=64), nullable=True),
        sa.Column("original_model_version", sa.String(length=64), nullable=True),
        sa.Column("selected_category_id", sa.Uuid(), nullable=False),
        sa.Column("selected_category_code", sa.String(length=64), nullable=True),
        sa.Column("merchant_memory_id", sa.Uuid(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"original_category_code IS NULL OR original_category_code IN "
            f"({_quoted(_CATEGORY_CODES)})",
            name=op.f(
                "ck_transaction_category_corrections_original_category_code_allowed"
            ),
        ),
        sa.CheckConstraint(
            "original_confidence >= 0 AND original_confidence <= 1",
            name=op.f(
                "ck_transaction_category_corrections_original_confidence_bounded"
            ),
        ),
        sa.CheckConstraint(
            "original_decision IN ('automatic', 'suggested', 'abstained')",
            name=op.f("ck_transaction_category_corrections_original_decision_allowed"),
        ),
        sa.CheckConstraint(
            "cardinality(original_reason_codes) BETWEEN 1 AND 5",
            name=op.f(
                "ck_transaction_category_corrections_original_reason_codes_bounded"
            ),
        ),
        sa.CheckConstraint(
            f"original_reason_codes <@ ARRAY[{_quoted(_REASON_CODES)}]::varchar[]",
            name=op.f(
                "ck_transaction_category_corrections_original_reason_codes_allowed"
            ),
        ),
        sa.CheckConstraint(
            "original_source IN ('rule', 'merchant_memory', 'ml', 'hybrid')",
            name=op.f("ck_transaction_category_corrections_original_source_allowed"),
        ),
        sa.CheckConstraint(
            "((original_source IN ('rule', 'hybrid')) = "
            "(original_ruleset_version IS NOT NULL)) AND "
            "((original_source IN ('ml', 'hybrid')) = "
            "(original_model_version IS NOT NULL))",
            name=op.f(
                "ck_transaction_category_corrections_original_source_version_consistent"
            ),
        ),
        sa.CheckConstraint(
            "original_model_version IS NULL OR "
            "length(trim(original_model_version)) > 0",
            name=op.f(
                "ck_transaction_category_corrections_original_model_version_not_blank"
            ),
        ),
        sa.CheckConstraint(
            "original_ruleset_version IS NULL OR "
            "length(trim(original_ruleset_version)) > 0",
            name=op.f(
                "ck_transaction_category_corrections_original_ruleset_version_not_blank"
            ),
        ),
        sa.CheckConstraint(
            "original_subcategory_code IS NULL OR "
            f"original_subcategory_code IN ({_quoted(_SUBCATEGORY_CODES)})",
            name=op.f(
                "ck_transaction_category_corrections_original_subcategory_code_allowed"
            ),
        ),
        sa.CheckConstraint(
            "length(trim(original_taxonomy_version)) > 0",
            name=op.f(
                "ck_transaction_category_corrections_original_taxonomy_version_not_blank"
            ),
        ),
        sa.CheckConstraint(
            "(original_decision = 'abstained' AND "
            "original_category_code IS NULL AND "
            "original_subcategory_code IS NULL) OR "
            "(original_decision <> 'abstained' AND "
            "original_category_code IS NOT NULL AND "
            "original_subcategory_code IS NOT NULL)",
            name=op.f("ck_transaction_category_corrections_original_target_consistent"),
        ),
        sa.CheckConstraint(
            "selected_category_code IS NULL OR "
            f"selected_category_code IN ({_quoted(_SUBCATEGORY_CODES)})",
            name=op.f(
                "ck_transaction_category_corrections_selected_category_code_allowed"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "transaction_id", "classification_id"],
            [
                "transaction_classifications.user_id",
                "transaction_classifications.transaction_id",
                "transaction_classifications.id",
            ],
            name=("fk_transaction_category_corrections_original_classification"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "transaction_id"],
            ["transactions.user_id", "transactions.id"],
            name="fk_transaction_category_corrections_owner_transaction",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["selected_category_id"],
            ["categories.id"],
            name="fk_transaction_category_corrections_selected_category",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_transaction_category_corrections_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transaction_category_corrections")),
    )
    op.create_index(
        "ix_transaction_category_corrections_transaction_occurred",
        "transaction_category_corrections",
        ["transaction_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_transaction_category_corrections_user_occurred",
        "transaction_category_corrections",
        ["user_id", "occurred_at"],
        unique=False,
    )
    op.execute(
        """
        CREATE FUNCTION reject_transaction_category_correction_update()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'transaction category corrections are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_transaction_category_corrections_immutable
        BEFORE UPDATE ON transaction_category_corrections
        FOR EACH ROW
        EXECUTE FUNCTION reject_transaction_category_correction_update()
        """
    )


def downgrade() -> None:
    """Remove correction feedback and exact personal merchant mappings."""
    op.execute(
        "DROP TRIGGER trg_transaction_category_corrections_immutable "
        "ON transaction_category_corrections"
    )
    op.execute("DROP FUNCTION reject_transaction_category_correction_update()")
    op.drop_index(
        "ix_transaction_category_corrections_user_occurred",
        table_name="transaction_category_corrections",
    )
    op.drop_index(
        "ix_transaction_category_corrections_transaction_occurred",
        table_name="transaction_category_corrections",
    )
    op.drop_table("transaction_category_corrections")
    op.drop_index(
        "ix_user_merchant_memories_user_updated",
        table_name="user_merchant_memories",
    )
    op.drop_table("user_merchant_memories")
    op.drop_constraint(
        "uq_transaction_classifications_owner_transaction_id",
        "transaction_classifications",
        type_="unique",
    )
