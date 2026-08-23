"""User-scoped persistence for transaction classification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import blake2b
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.classification.hybrid import HybridClassificationOutcome
from falcon_api.classification.taxonomy import (
    CLASSIFICATION_TAXONOMY_VERSION,
    ClassificationCategoryCode,
    ClassificationSubcategoryCode,
)
from falcon_api.models.account import Account
from falcon_api.models.category import Category
from falcon_api.models.classification import (
    TransactionCategoryCorrection,
    TransactionClassification,
    UserMerchantMemory,
)
from falcon_api.models.ledger import Transaction


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

    async def get_latest_correction(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        transaction_id: UUID,
    ) -> TransactionCategoryCorrection | None:
        """Return the latest trusted correction for one owned transaction."""
        statement = (
            select(TransactionCategoryCorrection)
            .where(
                TransactionCategoryCorrection.user_id == user_id,
                TransactionCategoryCorrection.transaction_id == transaction_id,
            )
            .order_by(
                TransactionCategoryCorrection.occurred_at.desc(),
                TransactionCategoryCorrection.id.desc(),
            )
            .limit(1)
        )
        return await session.scalar(statement)

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
            Category.classification_code.in_(code.value for code in subcategory_codes),
            Category.is_system.is_(True),
            Category.user_id.is_(None),
            Category.archived_at.is_(None),
        )
        rows = await session.scalars(statement)
        return tuple(rows.all())

    async def get_active_category(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        category_id: UUID,
    ) -> Category | None:
        """Return one active system or same-user private category."""
        statement = select(Category).where(
            Category.id == category_id,
            Category.archived_at.is_(None),
            or_(
                and_(
                    Category.is_system.is_(True),
                    Category.user_id.is_(None),
                ),
                and_(
                    Category.is_system.is_(False),
                    Category.user_id == user_id,
                ),
            ),
        )
        return await session.scalar(statement)

    async def get_merchant_memories(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        normalized_merchants: frozenset[str],
    ) -> tuple[UserMerchantMemory, ...]:
        """Resolve exact same-user mappings in one bounded query."""
        if not normalized_merchants:
            return ()
        statement = select(UserMerchantMemory).where(
            UserMerchantMemory.user_id == user_id,
            UserMerchantMemory.normalized_merchant.in_(normalized_merchants),
            UserMerchantMemory.taxonomy_version == CLASSIFICATION_TAXONOMY_VERSION,
        )
        rows = await session.scalars(statement)
        return tuple(rows.all())

    async def list_merchant_memories(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        after: str | None,
        limit: int,
    ) -> tuple[tuple[UserMerchantMemory, ...], bool]:
        """Return one stable exact-merchant page for one owner."""
        predicates = [
            UserMerchantMemory.user_id == user_id,
            UserMerchantMemory.taxonomy_version
            == CLASSIFICATION_TAXONOMY_VERSION,
        ]
        if after is not None:
            predicates.append(UserMerchantMemory.normalized_merchant > after)
        statement = (
            select(UserMerchantMemory)
            .where(*predicates)
            .order_by(UserMerchantMemory.normalized_merchant.asc())
            .limit(limit + 1)
        )
        rows = tuple((await session.scalars(statement)).all())
        return rows[:limit], len(rows) > limit

    async def get_merchant_memory(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        memory_id: UUID,
        for_update: bool = False,
    ) -> UserMerchantMemory | None:
        """Return one mapping only through its owner namespace."""
        statement = select(UserMerchantMemory).where(
            UserMerchantMemory.user_id == user_id,
            UserMerchantMemory.id == memory_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await session.scalar(statement)

    async def upsert_merchant_memory(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        normalized_merchant: str,
        category_code: ClassificationCategoryCode,
        subcategory_code: ClassificationSubcategoryCode,
        category_id: UUID,
        now: datetime,
    ) -> UserMerchantMemory:
        """Serialize and create or replace one exact same-user mapping."""
        await _lock_memory_key(
            session,
            user_id=user_id,
            normalized_merchant=normalized_merchant,
        )
        statement = (
            select(UserMerchantMemory)
            .where(
                UserMerchantMemory.user_id == user_id,
                UserMerchantMemory.normalized_merchant == normalized_merchant,
            )
            .with_for_update()
        )
        memory = await session.scalar(statement)
        if memory is None:
            memory = UserMerchantMemory(
                id=uuid4(),
                user_id=user_id,
                normalized_merchant=normalized_merchant,
                category_id=category_id,
                category_code=category_code,
                subcategory_code=subcategory_code,
                taxonomy_version=CLASSIFICATION_TAXONOMY_VERSION,
                created_at=now,
                updated_at=now,
            )
            session.add(memory)
        else:
            memory.category_id = category_id
            memory.category_code = category_code
            memory.subcategory_code = subcategory_code
            memory.taxonomy_version = CLASSIFICATION_TAXONOMY_VERSION
            memory.updated_at = now
        await session.flush()
        return memory

    async def delete_merchant_memory(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        memory: UserMerchantMemory,
    ) -> None:
        """Delete one mapping after the application verifies ownership."""
        if memory.user_id != user_id:
            raise ValueError("Merchant memory does not belong to the user.")
        await session.delete(memory)
        await session.flush()

    async def delete_merchant_memory_by_name(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        normalized_merchant: str,
    ) -> None:
        """Remove a stale exact mapping when a private category is selected."""
        await _lock_memory_key(
            session,
            user_id=user_id,
            normalized_merchant=normalized_merchant,
        )
        statement = (
            select(UserMerchantMemory)
            .where(
                UserMerchantMemory.user_id == user_id,
                UserMerchantMemory.normalized_merchant == normalized_merchant,
            )
            .with_for_update()
        )
        memory = await session.scalar(statement)
        if memory is not None:
            await session.delete(memory)
            await session.flush()

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
                raise ValueError("Transaction does not belong to the specified user.")
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

    async def persist_correction(
        self,
        session: AsyncSession,
        *,
        user_id: UUID,
        target: ClassificationTarget,
        original: TransactionClassification,
        selected_category: Category,
        merchant_memory_id: UUID | None,
        now: datetime,
    ) -> TransactionCategoryCorrection:
        """Update the ledger and append a server-owned correction snapshot."""
        transaction = target.transaction
        if transaction.user_id != user_id or original.user_id != user_id:
            raise ValueError("Correction resources do not belong to the user.")
        if original.transaction_id != transaction.id:
            raise ValueError("Correction classification does not match transaction.")
        transaction.category_id = selected_category.id
        transaction.is_user_modified = True
        transaction.updated_at = now
        correction = TransactionCategoryCorrection(
            id=uuid4(),
            user_id=user_id,
            transaction_id=transaction.id,
            classification_id=original.id,
            original_decision=original.decision,
            original_source=original.source,
            original_category_code=original.category_code,
            original_subcategory_code=original.subcategory_code,
            original_confidence=original.confidence,
            original_reason_codes=list(original.reason_codes),
            original_taxonomy_version=original.taxonomy_version,
            original_ruleset_version=original.ruleset_version,
            original_model_version=original.model_version,
            selected_category_id=selected_category.id,
            selected_category_code=selected_category.classification_code,
            merchant_memory_id=merchant_memory_id,
            occurred_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(correction)
        await session.flush()
        return correction


async def _lock_memory_key(
    session: AsyncSession,
    *,
    user_id: UUID,
    normalized_merchant: str,
) -> None:
    """Take a transaction-scoped PostgreSQL lock for one owner/key pair."""
    digest = blake2b(
        user_id.bytes + normalized_merchant.encode("utf-8"),
        digest_size=8,
        person=b"falconmm",
    ).digest()
    key = int.from_bytes(digest, byteorder="big", signed=True)
    await session.execute(select(func.pg_advisory_xact_lock(key)))
