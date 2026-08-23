"""Authenticated, atomic transaction-classification workflows."""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.auth.clock import Clock, SystemClock
from falcon_api.classification.features import (
    ClassificationFeatures,
    TransactionFeatureInput,
    build_classification_features,
    normalize_merchant,
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
    ClassificationWrite,
)
from falcon_api.classification.taxonomy import (
    CLASSIFICATION_TAXONOMY_VERSION,
    ClassificationCategoryCode,
    ClassificationSubcategoryCode,
    subcategory_definition,
    validate_classification_target,
)
from falcon_api.classification.types import (
    ClassificationDecision,
    ClassificationReasonCode,
)
from falcon_api.core.errors import ApplicationError
from falcon_api.models.category import Category
from falcon_api.models.classification import (
    TransactionClassification,
    UserMerchantMemory,
)
from falcon_api.models.enums import CategoryKind, TransactionStatus, TransactionType
from falcon_api.schemas.classification import (
    ClassificationCorrectionResult,
    ClassificationResult,
    MerchantMemoryPageResponse,
    MerchantMemoryResult,
)

_MAX_BATCH_SIZE: Final = 100
_CLASSIFIABLE_TYPES: Final = frozenset(
    {TransactionType.INCOME, TransactionType.EXPENSE, TransactionType.TRANSFER}
)


class TransactionClassificationService:
    """Own authorization-safe prediction, assignment, and provenance policy."""

    def __init__(
        self,
        *,
        hybrid_service: HybridClassificationService,
        repository: ClassificationRepository | None = None,
        clock: Clock | None = None,
        monitor: ClassificationMonitor | None = None,
    ) -> None:
        if not isinstance(hybrid_service, HybridClassificationService):
            raise TypeError("hybrid_service must use the hybrid service contract.")
        self._hybrid = hybrid_service
        self._repository = repository or ClassificationRepository()
        self._clock = clock or SystemClock()
        self._monitor = monitor or ClassificationMonitor()

    async def classify_one(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        transaction_id: UUID,
    ) -> ClassificationResult:
        """Classify one owned transaction idempotently."""
        results = await self.classify_batch(
            session,
            user_id=user_id,
            transaction_ids=(transaction_id,),
        )
        return results[0]

    async def classify_batch(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        transaction_ids: tuple[UUID, ...],
    ) -> tuple[ClassificationResult, ...]:
        """Classify at most 100 owned transactions in one atomic request."""
        _validate_batch(transaction_ids)
        started_at = self._monitor.start()
        targets = await self._repository.lock_targets(
            session,
            user_id=user_id,
            transaction_ids=transaction_ids,
        )
        by_id = {target.transaction.id: target for target in targets}
        if len(by_id) != len(transaction_ids):
            raise _transaction_not_found()
        ordered_targets = tuple(by_id[item] for item in transaction_ids)

        existing_rows = await self._repository.get_existing(
            session,
            user_id=user_id,
            transaction_ids=transaction_ids,
        )
        existing = {item.transaction_id: item for item in existing_rows}
        results: dict[UUID, ClassificationResult] = {}
        feature_work: list[tuple[ClassificationTarget, ClassificationFeatures]] = []
        pending: list[tuple[ClassificationTarget, HybridClassificationOutcome]] = []

        for target in ordered_targets:
            stored = existing.get(target.transaction.id)
            if stored is not None:
                _require_unchanged_stored_target(target, stored)
                results[target.transaction.id] = _stored_result(stored)
                continue
            _require_classifiable(target)
            feature_work.append((target, _features_for(target)))

        merchant_names = frozenset(
            features.normalized_merchant
            for _, features in feature_work
            if features.normalized_merchant is not None
        )
        memories = await self._repository.get_merchant_memories(
            session,
            user_id=user_id,
            normalized_merchants=merchant_names,
        )
        memory_by_name: dict[str, MerchantMemoryMatch] = {}
        for memory in memories:
            try:
                memory_by_name[memory.normalized_merchant] = _memory_match(memory)
            except ValueError:
                continue
        for target, features in feature_work:
            memory = (
                memory_by_name.get(features.normalized_merchant)
                if features.normalized_merchant is not None
                else None
            )
            outcome = self._hybrid.classify(
                features,
                merchant_memory=memory,
            )
            if ClassificationReasonCode.CLASSIFIER_UNAVAILABLE in outcome.reason_codes:
                raise ApplicationError(
                    code="classification_unavailable",
                    message="Transaction classification is temporarily unavailable.",
                    status_code=422,
                )
            pending.append((target, outcome))

        category_codes = frozenset(
            outcome.subcategory
            for _, outcome in pending
            if outcome.decision is ClassificationDecision.AUTOMATIC
            and outcome.subcategory is not None
        )
        categories = await self._repository.get_system_categories(
            session,
            subcategory_codes=category_codes,
        )
        category_by_code = {
            ClassificationSubcategoryCode(category.classification_code): category
            for category in categories
            if category.classification_code is not None
        }
        writes: list[ClassificationWrite] = []
        for target, outcome in pending:
            assigned = None
            if outcome.decision is ClassificationDecision.AUTOMATIC:
                assert outcome.subcategory is not None
                assigned = category_by_code.get(outcome.subcategory)
                if assigned is None:
                    raise ApplicationError(
                        code="category_not_found",
                        message="The classification category was not found.",
                        status_code=404,
                    )
                _validate_assignment(target, outcome, assigned)
            writes.append(
                ClassificationWrite(
                    target=target,
                    outcome=outcome,
                    assigned_category=assigned,
                )
            )

        if writes:
            stored_rows = await self._repository.persist(
                session,
                user_id=user_id,
                writes=tuple(writes),
                now=self._clock.now(),
            )
            results.update(
                (stored.transaction_id, _stored_result(stored))
                for stored in stored_rows
            )
        ordered_results = tuple(results[item] for item in transaction_ids)
        self._monitor.record_classification(
            ordered_results,
            started_at=started_at,
        )
        return ordered_results

    async def correct_category(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        transaction_id: UUID,
        category_id: UUID,
    ) -> ClassificationCorrectionResult:
        """Append trusted correction feedback and update isolated memory."""
        started_at = self._monitor.start()
        targets = await self._repository.lock_targets(
            session,
            user_id=user_id,
            transaction_ids=(transaction_id,),
        )
        if len(targets) != 1:
            raise _transaction_not_found()
        target = targets[0]
        existing = await self._repository.get_existing(
            session,
            user_id=user_id,
            transaction_ids=(transaction_id,),
        )
        if len(existing) != 1:
            raise _classification_conflict(
                "A stored classification is required before correction."
            )
        original = existing[0]
        if target.transaction.is_user_modified:
            latest = await self._repository.get_latest_correction(
                session,
                user_id=user_id,
                transaction_id=transaction_id,
            )
            if (
                latest is None
                or target.transaction.updated_at != latest.occurred_at
            ):
                raise _classification_conflict(
                    "The transaction changed outside the correction workflow."
                )
        selected = await self._repository.get_active_category(
            session,
            user_id=user_id,
            category_id=category_id,
        )
        if selected is None:
            raise ApplicationError(
                code="category_not_found",
                message="The classification category was not found.",
                status_code=404,
            )
        _validate_selected_category(target, selected)

        features = _features_for(target)
        normalized = features.normalized_merchant
        memory: UserMerchantMemory | None = None
        now = self._clock.now()
        if normalized is not None and selected.classification_code is not None:
            category_code, subcategory_code = _taxonomy_target(selected)
            memory = await self._repository.upsert_merchant_memory(
                session,
                user_id=user_id,
                normalized_merchant=normalized,
                category_id=selected.id,
                category_code=category_code,
                subcategory_code=subcategory_code,
                now=now,
            )
        elif normalized is not None:
            await self._repository.delete_merchant_memory_by_name(
                session,
                user_id=user_id,
                normalized_merchant=normalized,
            )
        correction = await self._repository.persist_correction(
            session,
            user_id=user_id,
            target=target,
            original=original,
            selected_category=selected,
            merchant_memory_id=memory.id if memory is not None else None,
            now=now,
        )
        result = ClassificationCorrectionResult(
            id=correction.id,
            transaction_id=transaction_id,
            selected_category_id=selected.id,
            selected_category_code=selected.classification_code,
            merchant_memory_id=correction.merchant_memory_id,
            original=_stored_result(original),
            occurred_at=correction.occurred_at,
        )
        self._monitor.record_operation(
            ClassificationOperation.CORRECT,
            item_count=1,
            started_at=started_at,
        )
        return result

    async def set_merchant_memory(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        merchant_name: str,
        category_id: UUID,
    ) -> MerchantMemoryResult:
        """Create or replace one exact personal mapping without model training."""
        started_at = self._monitor.start()
        normalized = normalize_merchant(merchant_name)
        if normalized is None:
            raise ApplicationError(
                code="invalid_merchant_memory",
                message="The merchant name cannot produce a stable exact mapping.",
                status_code=422,
            )
        category = await self._repository.get_active_category(
            session,
            user_id=user_id,
            category_id=category_id,
        )
        if category is None:
            raise ApplicationError(
                code="category_not_found",
                message="The classification category was not found.",
                status_code=404,
            )
        if category.classification_code is None:
            raise ApplicationError(
                code="invalid_merchant_memory",
                message="Merchant memory requires a stable system category.",
                status_code=422,
            )
        try:
            category_code, subcategory_code = _taxonomy_target(category)
        except ValueError:
            raise ApplicationError(
                code="invalid_merchant_memory",
                message="Merchant memory requires a stable system category.",
                status_code=422,
            ) from None
        memory = await self._repository.upsert_merchant_memory(
            session,
            user_id=user_id,
            normalized_merchant=normalized,
            category_id=category.id,
            category_code=category_code,
            subcategory_code=subcategory_code,
            now=self._clock.now(),
        )
        result = _memory_result(memory)
        self._monitor.record_operation(
            ClassificationOperation.MERCHANT_MEMORY_UPSERT,
            item_count=1,
            started_at=started_at,
        )
        return result

    async def list_merchant_memories(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        after: str | None,
        limit: int,
    ) -> MerchantMemoryPageResponse:
        """List a bounded stable page without exposing ownership fields."""
        started_at = self._monitor.start()
        items, has_more = await self._repository.list_merchant_memories(
            session,
            user_id=user_id,
            after=after,
            limit=limit,
        )
        result = MerchantMemoryPageResponse(
            items=tuple(_memory_result(item) for item in items),
            next_cursor=(items[-1].normalized_merchant if has_more else None),
        )
        self._monitor.record_operation(
            ClassificationOperation.MERCHANT_MEMORY_LIST,
            item_count=len(result.items),
            started_at=started_at,
        )
        return result

    async def delete_merchant_memory(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        memory_id: UUID,
    ) -> None:
        """Remove one exact mapping through a uniform owner-scoped lookup."""
        started_at = self._monitor.start()
        memory = await self._repository.get_merchant_memory(
            session,
            user_id=user_id,
            memory_id=memory_id,
            for_update=True,
        )
        if memory is None:
            raise ApplicationError(
                code="merchant_memory_not_found",
                message="The merchant memory was not found.",
                status_code=404,
            )
        await self._repository.delete_merchant_memory(
            session,
            user_id=user_id,
            memory=memory,
        )
        self._monitor.record_operation(
            ClassificationOperation.MERCHANT_MEMORY_DELETE,
            item_count=1,
            started_at=started_at,
        )


def _validate_batch(transaction_ids: tuple[UUID, ...]) -> None:
    if not transaction_ids or len(transaction_ids) > _MAX_BATCH_SIZE:
        raise ValueError("transaction_ids must contain one through 100 values.")
    if len(set(transaction_ids)) != len(transaction_ids):
        raise ValueError("transaction_ids must be unique.")


def _features_for(target: ClassificationTarget) -> ClassificationFeatures:
    transaction = target.transaction
    return build_classification_features(
        TransactionFeatureInput(
            description=transaction.description,
            merchant_name=transaction.merchant_name,
            transaction_type=TransactionType(transaction.transaction_type),
            signed_amount=transaction.amount,
            transaction_date=transaction.transaction_date,
            account_currency=target.account_currency,
        )
    )


def _memory_match(memory: UserMerchantMemory) -> MerchantMemoryMatch:
    if memory.taxonomy_version != CLASSIFICATION_TAXONOMY_VERSION:
        raise ValueError("Merchant memory taxonomy version is incompatible.")
    subcategory = ClassificationSubcategoryCode(memory.subcategory_code)
    category, _ = subcategory_definition(subcategory)
    if ClassificationCategoryCode(memory.category_code) is not category:
        raise ValueError("Merchant memory target is inconsistent.")
    return MerchantMemoryMatch(
        category=category,
        subcategory=subcategory,
    )


def _taxonomy_target(
    category: Category,
) -> tuple[ClassificationCategoryCode, ClassificationSubcategoryCode]:
    if category.classification_code is None:
        raise ValueError("Category has no stable taxonomy code.")
    try:
        subcategory = ClassificationSubcategoryCode(category.classification_code)
        category_code, definition = subcategory_definition(subcategory)
        if (
            not category.is_system
            or category.user_id is not None
            or CategoryKind(category.kind) is not definition.kind
        ):
            raise ValueError("Category is not a valid system taxonomy leaf.")
    except ValueError:
        raise ValueError("Category is not a valid system taxonomy leaf.") from None
    return category_code, subcategory


def _validate_selected_category(
    target: ClassificationTarget,
    category: Category,
) -> None:
    transaction_type = TransactionType(target.transaction.transaction_type)
    if (
        TransactionStatus(target.transaction.status) is not TransactionStatus.POSTED
        or transaction_type not in _CLASSIFIABLE_TYPES
    ):
        raise ApplicationError(
            code="invalid_classification_target",
            message="The transaction cannot accept a classification correction.",
            status_code=422,
        )
    expected_type = {
        CategoryKind.INCOME: TransactionType.INCOME,
        CategoryKind.EXPENSE: TransactionType.EXPENSE,
        CategoryKind.TRANSFER: TransactionType.TRANSFER,
    }[CategoryKind(category.kind)]
    if transaction_type is not expected_type:
        raise ApplicationError(
            code="invalid_classification_target",
            message="The selected category is incompatible with the transaction.",
            status_code=422,
        )
    if category.classification_code is not None:
        try:
            category_code, subcategory = _taxonomy_target(category)
            validate_classification_target(
                category=category_code,
                subcategory=subcategory,
                transaction_type=transaction_type,
            )
        except ValueError:
            raise ApplicationError(
                code="invalid_classification_target",
                message="The selected category is incompatible with the transaction.",
                status_code=422,
            ) from None


def _memory_result(memory: UserMerchantMemory) -> MerchantMemoryResult:
    return MerchantMemoryResult(
        id=memory.id,
        normalized_merchant=memory.normalized_merchant,
        category_id=memory.category_id,
        category_code=ClassificationCategoryCode(memory.category_code),
        subcategory_code=ClassificationSubcategoryCode(memory.subcategory_code),
        taxonomy_version=memory.taxonomy_version,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
    )


def _require_classifiable(target: ClassificationTarget) -> None:
    transaction = target.transaction
    if transaction.category_id is not None or transaction.is_user_modified:
        raise _classification_conflict()
    if (
        TransactionStatus(transaction.status) is not TransactionStatus.POSTED
        or TransactionType(transaction.transaction_type) not in _CLASSIFIABLE_TYPES
    ):
        raise ApplicationError(
            code="invalid_classification_target",
            message="The transaction cannot be classified.",
            status_code=422,
        )


def _require_unchanged_stored_target(
    target: ClassificationTarget,
    stored: TransactionClassification,
) -> None:
    transaction = target.transaction
    if transaction.is_user_modified:
        raise _classification_conflict()
    if ClassificationDecision(stored.decision) is ClassificationDecision.AUTOMATIC:
        if (
            stored.assigned_category_id is None
            or transaction.category_id != stored.assigned_category_id
        ):
            raise _classification_conflict()
    elif transaction.category_id is not None:
        raise _classification_conflict()


def _validate_assignment(
    target: ClassificationTarget,
    outcome: HybridClassificationOutcome,
    category: Category,
) -> None:
    if outcome.category is None or outcome.subcategory is None:
        raise ApplicationError(
            code="invalid_classification_target",
            message="The classification target is invalid.",
            status_code=422,
        )
    try:
        validate_classification_target(
            category=outcome.category,
            subcategory=outcome.subcategory,
            transaction_type=target.transaction.transaction_type,
        )
        expected_kind = subcategory_definition(outcome.subcategory)[1].kind
        if category.kind != expected_kind:
            raise ValueError("Category kind does not match taxonomy.")
    except ValueError:
        raise ApplicationError(
            code="invalid_classification_target",
            message="The classification target is invalid.",
            status_code=422,
        ) from None


def _stored_result(stored: TransactionClassification) -> ClassificationResult:
    return ClassificationResult(
        transaction_id=stored.transaction_id,
        decision=stored.decision,
        source=stored.source,
        category_code=stored.category_code,
        subcategory_code=stored.subcategory_code,
        confidence=stored.confidence,
        reason_codes=tuple(
            ClassificationReasonCode(code) for code in stored.reason_codes
        ),
        taxonomy_version=stored.taxonomy_version,
        ruleset_version=stored.ruleset_version,
        model_version=stored.model_version,
    )


def _transaction_not_found() -> ApplicationError:
    return ApplicationError(
        code="transaction_not_found",
        message="The transaction was not found.",
        status_code=404,
    )


def _classification_conflict(
    message: str = "The transaction already has a protected category or changed state.",
) -> ApplicationError:
    return ApplicationError(
        code="classification_conflict",
        message=message,
        status_code=409,
    )
