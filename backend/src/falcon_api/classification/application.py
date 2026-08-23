"""Authenticated, atomic transaction-classification workflows."""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from falcon_api.auth.clock import Clock, SystemClock
from falcon_api.classification.features import (
    TransactionFeatureInput,
    build_classification_features,
)
from falcon_api.classification.hybrid import (
    HybridClassificationOutcome,
    HybridClassificationService,
)
from falcon_api.classification.repository import (
    ClassificationRepository,
    ClassificationTarget,
    ClassificationWrite,
)
from falcon_api.classification.taxonomy import (
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
from falcon_api.models.classification import TransactionClassification
from falcon_api.models.enums import TransactionStatus, TransactionType
from falcon_api.schemas.classification import ClassificationResult
from sqlalchemy.ext.asyncio import AsyncSession


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
    ) -> None:
        if not isinstance(hybrid_service, HybridClassificationService):
            raise TypeError("hybrid_service must use the hybrid service contract.")
        self._hybrid = hybrid_service
        self._repository = repository or ClassificationRepository()
        self._clock = clock or SystemClock()

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
        pending: list[tuple[ClassificationTarget, HybridClassificationOutcome]] = []

        for target in ordered_targets:
            stored = existing.get(target.transaction.id)
            if stored is not None:
                _require_unchanged_stored_target(target, stored)
                results[target.transaction.id] = _stored_result(stored)
                continue
            _require_classifiable(target)
            outcome = self._hybrid.classify(
                build_classification_features(
                    TransactionFeatureInput(
                        description=target.transaction.description,
                        merchant_name=target.transaction.merchant_name,
                        transaction_type=target.transaction.transaction_type,
                        signed_amount=target.transaction.amount,
                        transaction_date=target.transaction.transaction_date,
                        account_currency=target.account_currency,
                    )
                )
            )
            if (
                ClassificationReasonCode.CLASSIFIER_UNAVAILABLE
                in outcome.reason_codes
            ):
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
        return tuple(results[item] for item in transaction_ids)


def _validate_batch(transaction_ids: tuple[UUID, ...]) -> None:
    if not transaction_ids or len(transaction_ids) > _MAX_BATCH_SIZE:
        raise ValueError("transaction_ids must contain one through 100 values.")
    if len(set(transaction_ids)) != len(transaction_ids):
        raise ValueError("transaction_ids must be unique.")


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


def _classification_conflict() -> ApplicationError:
    return ApplicationError(
        code="classification_conflict",
        message="The transaction already has a protected category or changed state.",
        status_code=409,
    )
