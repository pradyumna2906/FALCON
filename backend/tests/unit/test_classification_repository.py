"""Persistence tests for owner-scoped transaction classifications."""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.classification.hybrid import HybridClassificationOutcome
from falcon_api.classification.repository import (
    ClassificationRepository,
    ClassificationTarget,
    ClassificationWrite,
)
from falcon_api.classification.taxonomy import (
    ClassificationCategoryCode,
    ClassificationSubcategoryCode,
)
from falcon_api.classification.types import (
    ClassificationDecision,
    ClassificationReasonCode,
    ClassificationSource,
)
from falcon_api.models.category import Category
from falcon_api.models.classification import (
    TransactionClassification,
    UserMerchantMemory,
)
from falcon_api.models.enums import (
    CategoryKind,
    TransactionSourceType,
    TransactionStatus,
    TransactionType,
)
from falcon_api.models.ledger import Transaction

_NOW = datetime(2026, 8, 23, 14, 0, tzinfo=UTC)


def _transaction(*, user_id=None) -> Transaction:
    return Transaction(
        id=uuid4(),
        user_id=user_id or uuid4(),
        account_id=uuid4(),
        category_id=None,
        import_job_id=None,
        transfer_group_id=None,
        transaction_type=TransactionType.EXPENSE,
        amount=Decimal("-500.0000"),
        transaction_date=date(2026, 8, 22),
        description="Swiggy order",
        merchant_name="Swiggy",
        source_type=TransactionSourceType.IMPORT,
        external_source_hash="b" * 64,
        status=TransactionStatus.POSTED,
        is_user_modified=False,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _category() -> Category:
    return Category(
        id=uuid4(),
        user_id=None,
        name="Food Delivery",
        normalized_name="food_delivery",
        classification_code="food_delivery",
        kind=CategoryKind.EXPENSE,
        parent_id=None,
        is_system=True,
        display_order=2,
        archived_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _outcome(
    decision: ClassificationDecision = ClassificationDecision.AUTOMATIC,
) -> HybridClassificationOutcome:
    return HybridClassificationOutcome(
        decision=decision,
        source=ClassificationSource.RULE,
        category=ClassificationCategoryCode.FOOD_DINING,
        subcategory=ClassificationSubcategoryCode.FOOD_DELIVERY,
        confidence=Decimal("0.9900"),
        reason_codes=(ClassificationReasonCode.KNOWN_MERCHANT,),
        ruleset_version="2026.1",
    )


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


def test_lock_targets_applies_owner_join_id_filter_and_row_lock() -> None:
    user_id = uuid4()
    transaction = _transaction(user_id=user_id)
    execution = Mock()
    execution.all.return_value = [(transaction, "INR")]
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = execution

    result = asyncio.run(
        ClassificationRepository().lock_targets(
            session,
            user_id=user_id,
            transaction_ids=(transaction.id,),
        )
    )

    assert result == (ClassificationTarget(transaction, "INR"),)
    statement = session.execute.await_args.args[0]
    query = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "transactions.user_id =" in query
    assert "transactions.id IN" in query
    assert "accounts.user_id = transactions.user_id" in query
    assert "ORDER BY transactions.id ASC" in query
    assert "FOR UPDATE OF transactions" in query


def test_existing_results_are_selected_under_owner_predicate() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.scalars.return_value = _Rows([])
    user_id = uuid4()
    transaction_id = uuid4()

    result = asyncio.run(
        ClassificationRepository().get_existing(
            session,
            user_id=user_id,
            transaction_ids=(transaction_id,),
        )
    )

    assert result == ()
    query = str(session.scalars.await_args.args[0])
    assert "transaction_classifications.user_id =" in query
    assert "transaction_classifications.transaction_id IN" in query


def test_latest_correction_is_owner_scoped_and_deterministically_ordered() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None

    result = asyncio.run(
        ClassificationRepository().get_latest_correction(
            session,
            user_id=uuid4(),
            transaction_id=uuid4(),
        )
    )

    assert result is None
    query = str(session.scalar.await_args.args[0])
    assert "transaction_category_corrections.user_id =" in query
    assert "transaction_category_corrections.transaction_id =" in query
    assert "transaction_category_corrections.occurred_at DESC" in query
    assert "transaction_category_corrections.id DESC" in query
    assert "LIMIT" in query


def test_system_category_lookup_is_active_global_and_taxonomy_scoped() -> None:
    session = AsyncMock(spec=AsyncSession)
    category = _category()
    session.scalars.return_value = _Rows([category])

    result = asyncio.run(
        ClassificationRepository().get_system_categories(
            session,
            subcategory_codes=frozenset({ClassificationSubcategoryCode.FOOD_DELIVERY}),
        )
    )

    assert result == (category,)
    query = str(session.scalars.await_args.args[0])
    assert "categories.classification_code IN" in query
    assert "categories.is_system IS true" in query
    assert "categories.user_id IS NULL" in query
    assert "categories.archived_at IS NULL" in query


def test_empty_category_lookup_avoids_database_round_trip() -> None:
    session = AsyncMock(spec=AsyncSession)

    result = asyncio.run(
        ClassificationRepository().get_system_categories(
            session, subcategory_codes=frozenset()
        )
    )

    assert result == ()
    session.scalars.assert_not_awaited()


def test_persist_assigns_automatic_category_and_bounded_provenance() -> None:
    user_id = uuid4()
    transaction = _transaction(user_id=user_id)
    category = _category()
    write = ClassificationWrite(
        target=ClassificationTarget(transaction, "INR"),
        outcome=_outcome(),
        assigned_category=category,
    )
    session = AsyncMock(spec=AsyncSession)

    stored = asyncio.run(
        ClassificationRepository().persist(
            session,
            user_id=user_id,
            writes=(write,),
            now=_NOW,
        )
    )[0]

    assert transaction.category_id == category.id
    assert transaction.updated_at == _NOW
    assert stored.user_id == user_id
    assert stored.transaction_id == transaction.id
    assert stored.assigned_category_id == category.id
    assert stored.reason_codes == ["known_merchant"]
    assert stored.taxonomy_version == "2026.1"
    session.add.assert_called_once_with(stored)
    session.flush.assert_awaited_once_with()


def test_persist_suggestion_does_not_assign_ledger_category() -> None:
    user_id = uuid4()
    transaction = _transaction(user_id=user_id)
    outcome = HybridClassificationOutcome(
        decision=ClassificationDecision.SUGGESTED,
        source=ClassificationSource.ML,
        category=ClassificationCategoryCode.FOOD_DINING,
        subcategory=ClassificationSubcategoryCode.FOOD_DELIVERY,
        confidence=Decimal("0.7000"),
        reason_codes=(ClassificationReasonCode.MODEL_PREDICTION,),
        model_version="classification_2026_1_demo.1",
    )
    session = AsyncMock(spec=AsyncSession)

    stored = asyncio.run(
        ClassificationRepository().persist(
            session,
            user_id=user_id,
            writes=(
                ClassificationWrite(
                    ClassificationTarget(transaction, "INR"), outcome, None
                ),
            ),
            now=_NOW,
        )
    )[0]

    assert transaction.category_id is None
    assert stored.assigned_category_id is None
    assert stored.decision is ClassificationDecision.SUGGESTED


def test_persist_rejects_a_mismatched_owner_before_flush() -> None:
    transaction = _transaction(user_id=uuid4())
    session = AsyncMock(spec=AsyncSession)

    with pytest.raises(ValueError, match="does not belong"):
        asyncio.run(
            ClassificationRepository().persist(
                session,
                user_id=uuid4(),
                writes=(
                    ClassificationWrite(
                        ClassificationTarget(transaction, "INR"),
                        _outcome(),
                        _category(),
                    ),
                ),
                now=_NOW,
            )
        )

    session.flush.assert_not_awaited()


def _memory(*, user_id, category: Category) -> UserMerchantMemory:
    return UserMerchantMemory(
        id=uuid4(),
        user_id=user_id,
        normalized_merchant="local cafe",
        category_id=category.id,
        category_code=ClassificationCategoryCode.FOOD_DINING,
        subcategory_code=ClassificationSubcategoryCode.RESTAURANTS,
        taxonomy_version="2026.1",
        created_at=_NOW,
        updated_at=_NOW,
    )


def test_merchant_memory_lookup_is_exact_versioned_and_owner_scoped() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.scalars.return_value = _Rows([])
    user_id = uuid4()

    result = asyncio.run(
        ClassificationRepository().get_merchant_memories(
            session,
            user_id=user_id,
            normalized_merchants=frozenset({"local cafe"}),
        )
    )

    assert result == ()
    query = str(session.scalars.await_args.args[0])
    assert "user_merchant_memories.user_id =" in query
    assert "user_merchant_memories.normalized_merchant IN" in query
    assert "user_merchant_memories.taxonomy_version =" in query


def test_upsert_memory_serializes_key_and_replaces_existing_mapping() -> None:
    user_id = uuid4()
    category = _category()
    memory = _memory(user_id=user_id, category=category)
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = memory

    result = asyncio.run(
        ClassificationRepository().upsert_merchant_memory(
            session,
            user_id=user_id,
            normalized_merchant="local cafe",
            category_id=category.id,
            category_code=ClassificationCategoryCode.FOOD_DINING,
            subcategory_code=ClassificationSubcategoryCode.FOOD_DELIVERY,
            now=_NOW,
        )
    )

    assert result is memory
    assert memory.subcategory_code is ClassificationSubcategoryCode.FOOD_DELIVERY
    assert session.execute.await_count == 1
    advisory_query = str(session.execute.await_args.args[0])
    assert "pg_advisory_xact_lock" in advisory_query
    session.flush.assert_awaited_once_with()


def test_correction_persistence_snapshots_original_and_marks_user_reviewed() -> None:
    user_id = uuid4()
    transaction = _transaction(user_id=user_id)
    selected = _category()
    original = TransactionClassification(
        id=uuid4(),
        user_id=user_id,
        transaction_id=transaction.id,
        assigned_category_id=None,
        decision=ClassificationDecision.SUGGESTED,
        source=ClassificationSource.ML,
        category_code=ClassificationCategoryCode.FOOD_DINING,
        subcategory_code=ClassificationSubcategoryCode.FOOD_DELIVERY,
        confidence=Decimal("0.7100"),
        reason_codes=[ClassificationReasonCode.MODEL_PREDICTION.value],
        taxonomy_version="2026.1",
        ruleset_version=None,
        model_version="classification_test.1",
        created_at=_NOW,
        updated_at=_NOW,
    )
    session = AsyncMock(spec=AsyncSession)

    correction = asyncio.run(
        ClassificationRepository().persist_correction(
            session,
            user_id=user_id,
            target=ClassificationTarget(transaction, "INR"),
            original=original,
            selected_category=selected,
            merchant_memory_id=uuid4(),
            now=_NOW,
        )
    )

    assert transaction.category_id == selected.id
    assert transaction.is_user_modified is True
    assert correction.classification_id == original.id
    assert correction.original_confidence == Decimal("0.7100")
    assert correction.selected_category_code == "food_delivery"
    session.add.assert_called_once_with(correction)
    session.flush.assert_awaited_once_with()


def test_memory_delete_rejects_mismatched_owner() -> None:
    category = _category()
    memory = _memory(user_id=uuid4(), category=category)
    session = AsyncMock(spec=AsyncSession)

    with pytest.raises(ValueError, match="does not belong"):
        asyncio.run(
            ClassificationRepository().delete_merchant_memory(
                session,
                user_id=uuid4(),
                memory=memory,
            )
        )

    session.delete.assert_not_awaited()
