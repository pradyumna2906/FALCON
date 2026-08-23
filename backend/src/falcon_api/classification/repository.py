"""User-scoped persistence for transaction classification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from falcon_api.classification.hybrid import HybridClassificationOutcome
from falcon_api.classification.taxonomy import ClassificationSubcategoryCode
from falcon_api.models.account import Account
from falcon_api.models.category import Category
from falcon_api.models.classification import TransactionClassification
from falcon_api.models.ledger import Transaction
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class ClassificationTarget:
    """One locked owned transaction plus its trusted account currency."""

    transaction: Transaction
    account_currency: str


@dataclass(frozen=True, slots=True)
class ClassificationWrite:
    """One validated result ready for atomic persistence."""

    target: ClassificationTarget
    outcome: HybridClassificationOutcome
    assigned_category: Category | None


class ClassificationRepository:
    """Persist classification data without crossing authenticated ownership."""

    async def lock_targets(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        transaction_ids: tuple[UUID, ...],
    ) -> tuple[ClassificationTarget, ...]:
        """Lock and return only selected transactions owned by one user."""
        statement = (
            select(Transaction, Account.currency)
            .join(
                Account,
                and_(
                    Account.user_id == Transaction.user_id,
                    Account.id == Transaction.account_id,
                ),
            )
            .where(
                Transaction.user_id == user_id,
                Transaction.id.in_(transaction_ids),
            )
            .order_by(Transaction.id.asc())
            .with_for_update(of=Transaction)
        )
        rows = (await session.execute(statement)).all()
        return tuple(
            ClassificationTarget(transaction=row[0], account_currency=row[1])
            for row in rows
        )

    async def get_existing(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        transaction_ids: tuple[UUID, ...],
    ) -> tuple[TransactionClassification, ...]:
        """Return persisted results under the same trusted owner predicate."""
        statement = select(TransactionClassification).where(
            TransactionClassification.user_id == user_id,
            TransactionClassification.transaction_id.in_(transaction_ids),
        )
        rows = await session.scalars(statement)
        return tuple(rows.all())

    async def get_system_categories(
        self,
        session: AsyncSession,
        *,
        subcategory_codes: frozenset[ClassificationSubcategoryCode],
    ) -> tuple[Category, ...]:
        """Resolve active system leaves used by automatic assignments."""
        if not subcategory_codes:
            return ()
        statement = select(Category).where(
            Category.classification_code.in_(
                code.value for code in subcategory_codes
            ),
            Category.is_system.is_(True),
            Category.user_id.is_(None),
            Category.archived_at.is_(None),
        )
        rows = await session.scalars(statement)
        return tuple(rows.all())

    async def persist(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        writes: tuple[ClassificationWrite, ...],
        now: datetime,
    ) -> tuple[TransactionClassification, ...]:
        """Apply automatic categories and add all provenance in one flush."""
        persisted: list[TransactionClassification] = []
        for write in writes:
            transaction = write.target.transaction
            if transaction.user_id != user_id:
                raise ValueError(
                    "Transaction does not belong to the specified user."
                )
            assigned_category_id = None
            if write.assigned_category is not None:
                assigned_category_id = write.assigned_category.id
                transaction.category_id = assigned_category_id
                transaction.updated_at = now
            outcome = write.outcome
            classification = TransactionClassification(
                id=uuid4(),
                user_id=user_id,
                transaction_id=transaction.id,
                assigned_category_id=assigned_category_id,
                decision=outcome.decision,
                source=outcome.source,
                category_code=outcome.category,
                subcategory_code=outcome.subcategory,
                confidence=outcome.confidence,
                reason_codes=[code.value for code in outcome.reason_codes],
                taxonomy_version=outcome.taxonomy_version,
                ruleset_version=outcome.ruleset_version,
                model_version=outcome.model_version,
                created_at=now,
                updated_at=now,
            )
            session.add(classification)
            persisted.append(classification)
        await session.flush()
        return tuple(persisted)
