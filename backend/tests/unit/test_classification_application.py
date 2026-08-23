"""Application-policy tests for authenticated transaction classification."""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from time import perf_counter
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
from falcon_api.auth.clock import Clock
from falcon_api.classification.application import (
    TransactionClassificationService,
)
from falcon_api.classification.hybrid import (
    HybridClassificationOutcome,
    HybridClassificationService,
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
from falcon_api.models.classification import TransactionClassification
from falcon_api.models.enums import (
    CategoryKind,
    TransactionSourceType,
    TransactionStatus,
    TransactionType,
)
from falcon_api.models.ledger import Transaction
from sqlalchemy.ext.asyncio import AsyncSession


_NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
_USER_ID = UUID("4df4946d-098f-481e-8476-12b17a6cd923")


def _transaction(
    *,
    transaction_id: UUID | None = None,
    transaction_type: TransactionType = TransactionType.EXPENSE,
    amount: Decimal = Decimal("-825.0000"),
    category_id: UUID | None = None,
    is_user_modified: bool = False,
    status: TransactionStatus = TransactionStatus.POSTED,
) -> Transaction:
    return Transaction(
        id=transaction_id or uuid4(),
        user_id=_USER_ID,
        account_id=uuid4(),
        category_id=category_id,
        import_job_id=None,
        transfer_group_id=(uuid4() if transaction_type is TransactionType.TRANSFER else None),
        transaction_type=transaction_type,
        amount=amount,
        transaction_date=date(2026, 8, 22),
        description="UPI Swiggy order",
        merchant_name="Swiggy",
        source_type=TransactionSourceType.IMPORT,
        external_source_hash="a" * 64,
        status=status,
        is_user_modified=is_user_modified,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _target(transaction: Transaction | None = None) -> ClassificationTarget:
    return ClassificationTarget(transaction or _transaction(), "INR")


def _category(
    *,
    category_id: UUID | None = None,
    code: str = "food_delivery",
    kind: CategoryKind = CategoryKind.EXPENSE,
) -> Category:
    return Category(
        id=category_id or uuid4(),
        user_id=None,
        name="Food Delivery",
        normalized_name=code,
        classification_code=code,
        kind=kind,
        parent_id=None,
        is_system=True,
        display_order=2,
        archived_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _automatic() -> HybridClassificationOutcome:
    return HybridClassificationOutcome(
        decision=ClassificationDecision.AUTOMATIC,
        source=ClassificationSource.RULE,
        category=ClassificationCategoryCode.FOOD_DINING,
        subcategory=ClassificationSubcategoryCode.FOOD_DELIVERY,
        confidence=Decimal("0.9900"),
        reason_codes=(ClassificationReasonCode.KNOWN_MERCHANT,),
        ruleset_version="2026.1",
    )


def _suggested() -> HybridClassificationOutcome:
    return HybridClassificationOutcome(
        decision=ClassificationDecision.SUGGESTED,
        source=ClassificationSource.ML,
        category=ClassificationCategoryCode.FOOD_DINING,
        subcategory=ClassificationSubcategoryCode.FOOD_DELIVERY,
        confidence=Decimal("0.7100"),
        reason_codes=(
            ClassificationReasonCode.MODEL_PREDICTION,
            ClassificationReasonCode.PROVISIONAL_MODEL,
        ),
        model_version="classification_2026_1_demo.1",
    )


def _stored(
    transaction: Transaction,
    outcome: HybridClassificationOutcome,
    *,
    assigned_category_id: UUID | None = None,
) -> TransactionClassification:
    return TransactionClassification(
        id=uuid4(),
        user_id=_USER_ID,
        transaction_id=transaction.id,
        assigned_category_id=assigned_category_id,
        decision=outcome.decision,
        source=outcome.source,
        category_code=outcome.category,
        subcategory_code=outcome.subcategory,
        confidence=outcome.confidence,
        reason_codes=[item.value for item in outcome.reason_codes],
        taxonomy_version=outcome.taxonomy_version,
        ruleset_version=outcome.ruleset_version,
        model_version=outcome.model_version,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _service(
    outcome: HybridClassificationOutcome,
) -> tuple[
    TransactionClassificationService,
    Mock,
    AsyncMock,
]:
    hybrid = Mock(spec=HybridClassificationService)
    hybrid.classify.return_value = outcome
    repository = AsyncMock(spec=ClassificationRepository)
    repository.get_existing.return_value = ()
    repository.get_merchant_memories.return_value = ()
    repository.get_system_categories.return_value = ()

    async def persist_side_effect(
        session,
        *,
        user_id,
        writes,
        now,
    ):
        return tuple(
            _stored(
                write.target.transaction,
                write.outcome,
                assigned_category_id=(
                    write.assigned_category.id
                    if write.assigned_category is not None
                    else None
                ),
            )
            for write in writes
        )

    repository.persist.side_effect = persist_side_effect
    clock = Mock(spec=Clock)
    clock.now.return_value = _NOW
    return (
        TransactionClassificationService(
            hybrid_service=hybrid,
            repository=repository,
            clock=clock,
        ),
        hybrid,
        repository,
    )


def test_classify_one_assigns_rule_category_and_persists_provenance() -> None:
    service, hybrid, repository = _service(_automatic())
    target = _target()
    category = _category()
    repository.lock_targets.return_value = (target,)
    repository.get_system_categories.return_value = (category,)
    session = AsyncMock(spec=AsyncSession)

    result = asyncio.run(
        service.classify_one(
            session,
            user_id=_USER_ID,
            transaction_id=target.transaction.id,
        )
    )

    assert result.decision is ClassificationDecision.AUTOMATIC
    assert result.subcategory_code is ClassificationSubcategoryCode.FOOD_DELIVERY
    hybrid.classify.assert_called_once()
    features = hybrid.classify.call_args.args[0]
    assert features.normalized_merchant == "swiggy"
    assert features.account_currency == "INR"
    write = repository.persist.await_args.kwargs["writes"][0]
    assert write.assigned_category is category


def test_suggestion_is_persisted_without_mutating_category() -> None:
    service, _, repository = _service(_suggested())
    target = _target()
    repository.lock_targets.return_value = (target,)
    session = AsyncMock(spec=AsyncSession)

    result = asyncio.run(
        service.classify_one(
            session,
            user_id=_USER_ID,
            transaction_id=target.transaction.id,
        )
    )

    assert result.decision is ClassificationDecision.SUGGESTED
    assert repository.persist.await_args.kwargs["writes"][0].assigned_category is None
    repository.get_system_categories.assert_awaited_once_with(
        session, subcategory_codes=frozenset()
    )


def test_existing_automatic_result_is_idempotent_without_inference() -> None:
    category_id = uuid4()
    transaction = _transaction(category_id=category_id)
    target = _target(transaction)
    stored = _stored(transaction, _automatic(), assigned_category_id=category_id)
    service, hybrid, repository = _service(_automatic())
    repository.lock_targets.return_value = (target,)
    repository.get_existing.return_value = (stored,)
    session = AsyncMock(spec=AsyncSession)

    result = asyncio.run(
        service.classify_one(
            session, user_id=_USER_ID, transaction_id=transaction.id
        )
    )

    assert result.transaction_id == transaction.id
    hybrid.classify.assert_not_called()
    repository.persist.assert_not_awaited()


def test_batch_preserves_request_order_for_stored_results() -> None:
    first = _transaction(category_id=uuid4())
    second = _transaction(category_id=uuid4())
    first_stored = _stored(
        first, _automatic(), assigned_category_id=first.category_id
    )
    second_stored = _stored(
        second, _automatic(), assigned_category_id=second.category_id
    )
    service, _, repository = _service(_automatic())
    repository.lock_targets.return_value = (_target(first), _target(second))
    repository.get_existing.return_value = (first_stored, second_stored)
    session = AsyncMock(spec=AsyncSession)

    results = asyncio.run(
        service.classify_batch(
            session,
            user_id=_USER_ID,
            transaction_ids=(second.id, first.id),
        )
    )

    assert tuple(item.transaction_id for item in results) == (second.id, first.id)


def test_maximum_batch_uses_bounded_repository_round_trips() -> None:
    """Guard the 100-item path against accidental per-transaction queries."""
    transactions = tuple(_transaction() for _ in range(100))
    service, hybrid, repository = _service(_automatic())
    repository.lock_targets.return_value = tuple(
        _target(transaction) for transaction in transactions
    )
    repository.get_system_categories.return_value = (_category(),)
    session = AsyncMock(spec=AsyncSession)

    started_at = perf_counter()
    results = asyncio.run(
        service.classify_batch(
            session,
            user_id=_USER_ID,
            transaction_ids=tuple(item.id for item in transactions),
        )
    )
    elapsed = perf_counter() - started_at

    assert len(results) == 100
    assert elapsed < 2.0
    assert hybrid.classify.call_count == 100
    repository.lock_targets.assert_awaited_once()
    repository.get_existing.assert_awaited_once()
    repository.get_merchant_memories.assert_awaited_once()
    repository.get_system_categories.assert_awaited_once()
    repository.persist.assert_awaited_once()


def test_missing_or_cross_user_transaction_is_uniform_not_found() -> None:
    service, _, repository = _service(_automatic())
    repository.lock_targets.return_value = ()

    with pytest.raises(ApplicationError) as captured:
        asyncio.run(
            service.classify_one(
                AsyncMock(spec=AsyncSession),
                user_id=_USER_ID,
                transaction_id=uuid4(),
            )
        )

    assert captured.value.code == "transaction_not_found"
    assert captured.value.status_code == 404
    repository.get_existing.assert_not_awaited()


@pytest.mark.parametrize(
    "transaction",
    [
        _transaction(category_id=uuid4()),
        _transaction(is_user_modified=True),
    ],
)
def test_new_classification_never_overwrites_user_state(
    transaction: Transaction,
) -> None:
    service, hybrid, repository = _service(_automatic())
    repository.lock_targets.return_value = (_target(transaction),)

    with pytest.raises(ApplicationError) as captured:
        asyncio.run(
            service.classify_one(
                AsyncMock(spec=AsyncSession),
                user_id=_USER_ID,
                transaction_id=transaction.id,
            )
        )

    assert captured.value.code == "classification_conflict"
    hybrid.classify.assert_not_called()
    repository.persist.assert_not_awaited()


def test_stored_suggestion_conflicts_after_user_category_selection() -> None:
    transaction = _transaction(category_id=uuid4())
    service, _, repository = _service(_suggested())
    repository.lock_targets.return_value = (_target(transaction),)
    repository.get_existing.return_value = (_stored(transaction, _suggested()),)

    with pytest.raises(ApplicationError, match="protected category") as captured:
        asyncio.run(
            service.classify_one(
                AsyncMock(spec=AsyncSession),
                user_id=_USER_ID,
                transaction_id=transaction.id,
            )
        )

    assert captured.value.code == "classification_conflict"


@pytest.mark.parametrize(
    "transaction",
    [
        _transaction(status=TransactionStatus.PENDING),
        _transaction(
            transaction_type=TransactionType.ADJUSTMENT,
            amount=Decimal("5.0000"),
        ),
    ],
)
def test_pending_and_adjustment_transactions_are_ineligible(
    transaction: Transaction,
) -> None:
    service, hybrid, repository = _service(_automatic())
    repository.lock_targets.return_value = (_target(transaction),)

    with pytest.raises(ApplicationError) as captured:
        asyncio.run(
            service.classify_one(
                AsyncMock(spec=AsyncSession),
                user_id=_USER_ID,
                transaction_id=transaction.id,
            )
        )

    assert captured.value.code == "invalid_classification_target"
    hybrid.classify.assert_not_called()


def test_classifier_unavailability_rolls_back_before_any_write() -> None:
    unavailable = HybridClassificationOutcome(
        decision=ClassificationDecision.ABSTAINED,
        source=ClassificationSource.ML,
        category=None,
        subcategory=None,
        confidence=Decimal("0"),
        reason_codes=(ClassificationReasonCode.CLASSIFIER_UNAVAILABLE,),
        model_version="classification_2026_1_demo.1",
    )
    service, _, repository = _service(unavailable)
    target = _target()
    repository.lock_targets.return_value = (target,)

    with pytest.raises(ApplicationError) as captured:
        asyncio.run(
            service.classify_one(
                AsyncMock(spec=AsyncSession),
                user_id=_USER_ID,
                transaction_id=target.transaction.id,
            )
        )

    assert captured.value.code == "classification_unavailable"
    repository.persist.assert_not_awaited()


def test_missing_automatic_taxonomy_category_aborts_batch() -> None:
    service, _, repository = _service(_automatic())
    target = _target()
    repository.lock_targets.return_value = (target,)

    with pytest.raises(ApplicationError) as captured:
        asyncio.run(
            service.classify_one(
                AsyncMock(spec=AsyncSession),
                user_id=_USER_ID,
                transaction_id=target.transaction.id,
            )
        )

    assert captured.value.code == "category_not_found"
    repository.persist.assert_not_awaited()


def test_wrong_kind_taxonomy_mapping_is_rejected() -> None:
    service, _, repository = _service(_automatic())
    target = _target()
    repository.lock_targets.return_value = (target,)
    repository.get_system_categories.return_value = (
        _category(kind=CategoryKind.INCOME),
    )

    with pytest.raises(ApplicationError) as captured:
        asyncio.run(
            service.classify_one(
                AsyncMock(spec=AsyncSession),
                user_id=_USER_ID,
                transaction_id=target.transaction.id,
            )
        )

    assert captured.value.code == "invalid_classification_target"


@pytest.mark.parametrize("transaction_ids", [(), tuple(uuid4() for _ in range(101))])
def test_service_enforces_batch_bound(transaction_ids: tuple[UUID, ...]) -> None:
    service, _, repository = _service(_automatic())

    with pytest.raises(ValueError, match="one through 100"):
        asyncio.run(
            service.classify_batch(
                AsyncMock(spec=AsyncSession),
                user_id=_USER_ID,
                transaction_ids=transaction_ids,
            )
        )

    repository.lock_targets.assert_not_awaited()


def test_service_rejects_duplicate_ids_and_invalid_hybrid_dependency() -> None:
    identifier = uuid4()
    service, _, _ = _service(_automatic())
    with pytest.raises(ValueError, match="must be unique"):
        asyncio.run(
            service.classify_batch(
                AsyncMock(spec=AsyncSession),
                user_id=_USER_ID,
                transaction_ids=(identifier, identifier),
            )
        )
    with pytest.raises(TypeError, match="hybrid_service"):
        TransactionClassificationService(hybrid_service=object())  # type: ignore[arg-type]
