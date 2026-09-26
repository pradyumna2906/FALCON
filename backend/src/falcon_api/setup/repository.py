"""Owner-scoped setup queries and bounded lists."""

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from falcon_api.models.account import Account, LiabilityDetail
from falcon_api.models.category import Category
from falcon_api.models.enums import CategoryKind
from falcon_api.models.import_job import ImportJob
from falcon_api.models.planning import Budget
from falcon_api.models.user import User


class SetupRepository:
    async def account(self, session, owner, identifier, *, lock=False):
        query = select(Account).where(
            Account.user_id == owner, Account.id == identifier
        )
        return await session.scalar(query.with_for_update() if lock else query)

    async def budget(self, session, owner, identifier, *, lock=False):
        query = (
            select(Budget)
            .options(selectinload(Budget.limits))
            .where(Budget.user_id == owner, Budget.id == identifier)
        )
        return await session.scalar(query.with_for_update() if lock else query)

    async def budgets(self, session, owner, *, limit, offset, archived):
        query = (
            select(Budget)
            .options(selectinload(Budget.limits))
            .where(Budget.user_id == owner)
        )
        if not archived:
            query = query.where(Budget.archived_at.is_(None))
        return tuple(
            (
                await session.scalars(
                    query.order_by(Budget.created_at.desc(), Budget.id.desc())
                    .offset(offset)
                    .limit(limit + 1)
                )
            ).all()
        )

    async def categories(self, session, owner, identifiers):
        if not identifiers:
            return ()
        return tuple(
            (
                await session.scalars(
                    select(Category)
                    .where(
                        Category.id.in_(identifiers),
                        Category.archived_at.is_(None),
                        Category.kind == CategoryKind.EXPENSE,
                        or_(Category.user_id == owner, Category.is_system.is_(True)),
                    )
                    .with_for_update()
                )
            ).all()
        )

    async def liability(self, session, owner, account_id):
        return await session.scalar(
            select(LiabilityDetail).where(
                LiabilityDetail.user_id == owner,
                LiabilityDetail.account_id == account_id,
            )
        )

    async def user(self, session, owner, *, lock=False):
        query = select(User).where(User.id == owner)
        return await session.scalar(query.with_for_update() if lock else query)

    async def imports(self, session, owner, *, limit, offset):
        return tuple(
            (
                await session.scalars(
                    select(ImportJob)
                    .options(selectinload(ImportJob.issues))
                    .where(ImportJob.user_id == owner)
                    .order_by(ImportJob.created_at.desc(), ImportJob.id.desc())
                    .offset(offset)
                    .limit(limit + 1)
                )
            ).all()
        )
