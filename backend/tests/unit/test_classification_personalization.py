"""Application tests for immutable corrections and isolated merchant memory."""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock, call
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.auth.clock import Clock
from falcon_api.classification.application import (
    TransactionClassificationService,
)
from falcon_api.classification.hybrid import (
    HybridClassificationOutcome,
    HybridClassificationService,
    MerchantMemoryMatch,
)
from falcon_api.classification.monitoring import (
    ClassificationMonitor,
    ClassificationOperation,
)
from falcon_api.classification.repository import (
    ClassificationRepository,
    ClassificationTarget,
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
from falcon_api.core.errors import ApplicationError
from falcon_api.models.category import Category
from falcon_api.models.classification import (
    TransactionCategoryCorrection,
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

_NOW = datetime(2026, 8, 23, 16, 0, tzinfo=UTC)
_USER_ID = UUID("ca3ded81-7238-46df-a389-c094527318b1")


def _transaction(
    *,
    merchant_name: str | None = "Local Cafe",
    transaction_type: TransactionType = TransactionType.EXPENSE,
    is_user_modified: bool = False,
) -> Transaction:
    amount = Decimal("-475.0000")
    if transaction_type is TransactionType.INCOME:
        amount = -amount
    return Transaction(
        id=uuid4(),
        user_id=_USER_ID,
        account_id=uuid4(),
        category_id=None,
        import_job_id=None,
        transfer_group_id=(
            uuid4() if transaction_type is TransactionType.TRANSFER else None
        ),
        transaction_type=transaction_type,
        amount=amount,
        transaction_date=date(2026, 8, 23),
        description="UPI Local Cafe purchase",
        merchant_name=merchant_name,
        source_type=TransactionSourceType.MANUAL,
        external_source_hash=None,
        status=TransactionStatus.POSTED,
        is_user_modified=is_user_modified,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _category(
    *,
    code: str | None = "restaurants",
    kind: CategoryKind = CategoryKind.EXPENSE,
    private: bool = False,
) -> Category:
    return Category(
        id=uuid4(),
        user_id=_USER_ID if private else None,
        name="Reviewed Category",
        normalized_name="reviewed_category",
        classification_code=code,
        kind=kind,
        parent_id=None,
        is_system=not private,
        display_order=1,
        archived_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _outcome() -> HybridClassificationOutcome:
    return HybridClassificationOutcome(
        decision=ClassificationDecision.AUTOMATIC,
        source=ClassificationSource.MERCHANT_MEMORY,
        category=ClassificationCategoryCode.FOOD_DINING,
        subcategory=ClassificationSubcategoryCode.RESTAURANTS,
        confidence=Decimal("1.0000"),
        reason_codes=(ClassificationReasonCode.USER_MERCHANT_MEMORY,),
    )


def _stored(transaction: Transaction) -> TransactionClassification:
    return TransactionClassification(
        id=uuid4(),
        user_id=_USER_ID,
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


def _memory(category: Category, *, merchant: str = "local cafe") -> UserMerchantMemory:
    return UserMerchantMemory(
        id=uuid4(),
        user_id=_USER_ID,
        normalized_merchant=merchant,
        category_id=category.id,
        category_code=ClassificationCategoryCode.FOOD_DINING,
        subcategory_code=ClassificationSubcategoryCode.RESTAURANTS,
        taxonomy_version="2026.1",
        created_at=_NOW,
        updated_at=_NOW,
    )


def _service(
    *, monitor: ClassificationMonitor | None = None
) -> tuple[
    TransactionClassificationService,
    Mock,
    AsyncMock,
]:
    hybrid = Mock(spec=HybridClassificationService)
    hybrid.classify.return_value = _outcome()
    repository = AsyncMock(spec=ClassificationRepository)
    repository.get_existing.return_value = ()
    repository.get_merchant_memories.return_value = ()
    repository.get_system_categories.return_value = ()
    clock = Mock(spec=Clock)
    clock.now.return_value = _NOW
    return (
        TransactionClassificationService(
            hybrid_service=hybrid,
            repository=repository,
            clock=clock,
            monitor=monitor,
        ),
        hybrid,
        repository,
    )


def test_batch_resolves_same_user_memories_once_before_hybrid_inference() -> None:
    monitor = Mock(spec=ClassificationMonitor)
    monitor.start.return_value = 1.0
    service, hybrid, repository = _service(monitor=monitor)
    transaction = _transaction()
    target = ClassificationTarget(transaction, "INR")
    category = _category()
    memory = _memory(category)
    repository.lock_targets.return_value = (target,)
    repository.get_merchant_memories.return_value = (memory,)
    repository.get_system_categories.return_value = (category,)
    repository.persist.return_value = (_stored(transaction),)
    session = AsyncMock(spec=AsyncSession)

    result = asyncio.run(
        service.classify_one(
            session,
            user_id=_USER_ID,
            transaction_id=transaction.id,
        )
    )

    repository.get_merchant_memories.assert_awaited_once_with(
        session,
        user_id=_USER_ID,
        normalized_merchants=frozenset({"local cafe"}),
    )
    match = hybrid.classify.call_args.kwargs["merchant_memory"]
    assert match == MerchantMemoryMatch(
        ClassificationCategoryCode.FOOD_DINING,
        ClassificationSubcategoryCode.RESTAURANTS,
    )
    monitor.record_classification.assert_called_once_with(
        (result,),
        started_at=1.0,
    )


def test_correction_appends_snapshot_updates_ledger_and_personal_memory() -> None:
    monitor = Mock(spec=ClassificationMonitor)
    monitor.start.return_value = 2.0
    service, _, repository = _service(monitor=monitor)
    transaction = _transaction()
    target = ClassificationTarget(transaction, "INR")
    original = _stored(transaction)
    selected = _category()
    memory = _memory(selected)
    correction = TransactionCategoryCorrection(
        id=uuid4(),
        user_id=_USER_ID,
        transaction_id=transaction.id,
        classification_id=original.id,
        original_decision=original.decision,
        original_source=original.source,
        original_category_code=original.category_code,
        original_subcategory_code=original.subcategory_code,
        original_confidence=original.confidence,
        original_reason_codes=list(original.reason_codes),
        original_taxonomy_version=original.taxonomy_version,
        original_ruleset_version=None,
        original_model_version=original.model_version,
        selected_category_id=selected.id,
        selected_category_code=selected.classification_code,
        merchant_memory_id=memory.id,
        occurred_at=_NOW,
        created_at=_NOW,
        updated_at=_NOW,
    )
    repository.lock_targets.return_value = (target,)
    repository.get_existing.return_value = (original,)
    repository.get_active_category.return_value = selected
    repository.upsert_merchant_memory.return_value = memory
    repository.persist_correction.return_value = correction
    session = AsyncMock(spec=AsyncSession)

    result = asyncio.run(
        service.correct_category(
            session,
            user_id=_USER_ID,
            transaction_id=transaction.id,
            category_id=selected.id,
        )
    )

    assert result.id == correction.id
    assert result.original.transaction_id == transaction.id
    assert result.original.confidence == Decimal("0.7100")
    assert result.merchant_memory_id == memory.id
    repository.upsert_merchant_memory.assert_awaited_once()
    memory_call = repository.upsert_merchant_memory.await_args.kwargs
    assert memory_call["normalized_merchant"] == "local cafe"
    assert memory_call["subcategory_code"] is ClassificationSubcategoryCode.RESTAURANTS
    repository.persist_correction.assert_awaited_once()
    monitor.record_operation.assert_called_once_with(
        ClassificationOperation.CORRECT,
        item_count=1,
        started_at=2.0,
    )


def test_private_category_correction_removes_stale_taxonomy_memory() -> None:
    service, _, repository = _service()
    transaction = _transaction()
    original = _stored(transaction)
    selected = _category(code=None, private=True)
    correction = Mock(
        id=uuid4(),
        merchant_memory_id=None,
        occurred_at=_NOW,
    )
    repository.lock_targets.return_value = (ClassificationTarget(transaction, "INR"),)
    repository.get_existing.return_value = (original,)
    repository.get_active_category.return_value = selected
    repository.persist_correction.return_value = correction

    result = asyncio.run(
        service.correct_category(
            AsyncMock(spec=AsyncSession),
            user_id=_USER_ID,
            transaction_id=transaction.id,
            category_id=selected.id,
        )
    )

    assert result.selected_category_code is None
    repository.delete_merchant_memory_by_name.assert_awaited_once()
    repository.upsert_merchant_memory.assert_not_awaited()


def test_correction_requires_owned_transaction_stored_prediction_and_kind() -> None:
    service, _, repository = _service()
    transaction = _transaction()
    session = AsyncMock(spec=AsyncSession)

    repository.lock_targets.return_value = ()
    with pytest.raises(ApplicationError) as missing:
        asyncio.run(
            service.correct_category(
                session,
                user_id=_USER_ID,
                transaction_id=transaction.id,
                category_id=uuid4(),
            )
        )
    assert missing.value.code == "transaction_not_found"

    repository.lock_targets.return_value = (ClassificationTarget(transaction, "INR"),)
    repository.get_existing.return_value = ()
    with pytest.raises(ApplicationError) as no_prediction:
        asyncio.run(
            service.correct_category(
                session,
                user_id=_USER_ID,
                transaction_id=transaction.id,
                category_id=uuid4(),
            )
        )
    assert no_prediction.value.code == "classification_conflict"

    repository.get_existing.return_value = (_stored(transaction),)
    repository.get_active_category.return_value = _category(
        code="salary", kind=CategoryKind.INCOME
    )
    with pytest.raises(ApplicationError) as incompatible:
        asyncio.run(
            service.correct_category(
                session,
                user_id=_USER_ID,
                transaction_id=transaction.id,
                category_id=uuid4(),
            )
        )
    assert incompatible.value.code == "invalid_classification_target"


def test_correction_rejects_transaction_changed_outside_review_workflow() -> None:
    service, _, repository = _service()
    transaction = _transaction(is_user_modified=True)
    repository.lock_targets.return_value = (
        ClassificationTarget(transaction, "INR"),
    )
    repository.get_existing.return_value = (_stored(transaction),)
    repository.get_latest_correction.return_value = None

    with pytest.raises(ApplicationError) as changed:
        asyncio.run(
            service.correct_category(
                AsyncMock(spec=AsyncSession),
                user_id=_USER_ID,
                transaction_id=transaction.id,
                category_id=uuid4(),
            )
        )

    assert changed.value.code == "classification_conflict"
    repository.get_active_category.assert_not_awaited()


def test_memory_management_is_normalized_bounded_and_owner_scoped() -> None:
    monitor = Mock(spec=ClassificationMonitor)
    monitor.start.side_effect = (3.0, 4.0, 5.0)
    service, _, repository = _service(monitor=monitor)
    category = _category()
    memory = _memory(category)
    repository.get_active_category.return_value = category
    repository.upsert_merchant_memory.return_value = memory
    repository.list_merchant_memories.return_value = ((memory,), True)
    repository.get_merchant_memory.return_value = memory
    session = AsyncMock(spec=AsyncSession)

    saved = asyncio.run(
        service.set_merchant_memory(
            session,
            user_id=_USER_ID,
            merchant_name="  Local Cafe UPI  ",
            category_id=category.id,
        )
    )
    page = asyncio.run(
        service.list_merchant_memories(
            session,
            user_id=_USER_ID,
            after=None,
            limit=50,
        )
    )
    asyncio.run(
        service.delete_merchant_memory(
            session,
            user_id=_USER_ID,
            memory_id=memory.id,
        )
    )

    assert saved.normalized_merchant == "local cafe"
    assert page.items == (saved,)
    assert page.next_cursor == "local cafe"
    repository.delete_merchant_memory.assert_awaited_once_with(
        session,
        user_id=_USER_ID,
        memory=memory,
    )
    assert monitor.record_operation.call_args_list == [
        call(
            ClassificationOperation.MERCHANT_MEMORY_UPSERT,
            item_count=1,
            started_at=3.0,
        ),
        call(
            ClassificationOperation.MERCHANT_MEMORY_LIST,
            item_count=1,
            started_at=4.0,
        ),
        call(
            ClassificationOperation.MERCHANT_MEMORY_DELETE,
            item_count=1,
            started_at=5.0,
        ),
    ]


def test_memory_management_rejects_noise_private_category_and_foreign_id() -> None:
    service, _, repository = _service()
    session = AsyncMock(spec=AsyncSession)

    with pytest.raises(ApplicationError) as noise:
        asyncio.run(
            service.set_merchant_memory(
                session,
                user_id=_USER_ID,
                merchant_name="UPI payment",
                category_id=uuid4(),
            )
        )
    assert noise.value.code == "invalid_merchant_memory"

    repository.get_active_category.return_value = _category(code=None, private=True)
    with pytest.raises(ApplicationError) as private:
        asyncio.run(
            service.set_merchant_memory(
                session,
                user_id=_USER_ID,
                merchant_name="Local Cafe",
                category_id=uuid4(),
            )
        )
    assert private.value.code == "invalid_merchant_memory"

    repository.get_merchant_memory.return_value = None
    with pytest.raises(ApplicationError) as foreign:
        asyncio.run(
            service.delete_merchant_memory(
                session,
                user_id=_USER_ID,
                memory_id=uuid4(),
            )
        )
    assert foreign.value.code == "merchant_memory_not_found"
