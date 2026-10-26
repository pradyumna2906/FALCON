"""Atomic setup workflows without client-supplied ownership."""

from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from falcon_api.auth.clock import SystemClock
from falcon_api.core.errors import ApplicationError
from falcon_api.models.account import LiabilityDetail
from falcon_api.models.planning import Budget, BudgetLimit
from falcon_api.setup.repository import SetupRepository


def missing():
    return ApplicationError(
        code="resource_not_found",
        message="The resource was not found.",
        status_code=404,
    )


def active(resource):
    if resource is None:
        raise missing()
    if resource.archived_at is not None:
        raise ApplicationError(
            code="resource_archived",
            message="Archived resources cannot be changed.",
            status_code=409,
        )
    return resource


class SetupService:
    def __init__(self, repository=None, clock=None):
        self.repository = repository or SetupRepository()
        self.clock = clock or SystemClock()

    async def get_account(self, session, owner, identifier):
        result = await self.repository.account(session, owner, identifier)
        if result is None:
            raise missing()
        return result

    async def update_account(self, session, owner, identifier, payload):
        try:
            async with session.begin_nested():
                account = active(
                    await self.repository.account(session, owner, identifier, lock=True)
                )
                for key, value in payload.model_dump().items():
                    setattr(account, key, value)
                account.updated_at = self.clock.now()
                await session.flush()
                return account
        except IntegrityError as exc:
            self._conflict(exc, "uq_accounts_user_name")

    async def archive_account(self, session, owner, identifier):
        account = await self.repository.account(session, owner, identifier, lock=True)
        if account is None:
            raise missing()
        if account.archived_at is None:
            account.archived_at = account.updated_at = self.clock.now()
            await session.flush()
        return account

    async def get_liability(self, session, owner, identifier):
        await self.get_account(session, owner, identifier)
        detail = await self.repository.liability(session, owner, identifier)
        if detail is None:
            raise missing()
        return detail

    async def put_liability(self, session, owner, identifier, payload):
        account = active(
            await self.repository.account(session, owner, identifier, lock=True)
        )
        if account.account_type != payload.liability_subtype.value:
            raise ApplicationError(
                code="liability_type_mismatch",
                message="Liability subtype must match a debt account.",
                status_code=422,
            )
        detail = await self.repository.liability(session, owner, identifier)
        now = self.clock.now()
        if detail is None:
            detail = LiabilityDetail(
                id=uuid4(), user_id=owner, account_id=identifier, created_at=now
            )
            session.add(detail)
        for key, value in payload.model_dump().items():
            setattr(detail, key, value)
        detail.updated_at = now
        await session.flush()
        return detail

    async def get_budget(self, session, owner, identifier):
        result = await self.repository.budget(session, owner, identifier)
        if result is None:
            raise missing()
        return result

    async def put_budget(self, session, owner, payload, identifier=None):
        try:
            async with session.begin_nested():
                now = self.clock.now()
                budget = (
                    active(
                        await self.repository.budget(
                            session, owner, identifier, lock=True
                        )
                    )
                    if identifier
                    else None
                )
                ids = tuple(item.category_id for item in payload.limits)
                categories = await self.repository.categories(session, owner, ids)
                if {item.id for item in categories} != set(ids):
                    raise missing()
                if budget is None:
                    budget = Budget(
                        id=uuid4(), user_id=owner, created_at=now, limits=[]
                    )
                    session.add(budget)
                else:
                    budget.limits.clear()
                    await session.flush()
                for key, value in payload.model_dump(exclude={"limits"}).items():
                    setattr(budget, key, value)
                budget.updated_at = now
                budget.limits = [
                    BudgetLimit(
                        id=uuid4(),
                        user_id=owner,
                        budget_id=budget.id,
                        category_id=item.category_id,
                        limit_amount=item.limit_amount,
                        created_at=now,
                        updated_at=now,
                    )
                    for item in payload.limits
                ]
                await session.flush()
                return budget
        except IntegrityError as exc:
            self._conflict(exc, "uq_budgets_user_name_period")

    async def archive_budget(self, session, owner, identifier):
        budget = await self.repository.budget(session, owner, identifier, lock=True)
        if budget is None:
            raise missing()
        if budget.archived_at is None:
            budget.archived_at = budget.updated_at = self.clock.now()
            await session.flush()
        return budget

    async def preferences(self, session, owner, payload=None):
        user = await self.repository.user(session, owner, lock=payload is not None)
        if user is None:
            raise missing()
        if payload is not None:
            for key, value in payload.model_dump().items():
                setattr(user, key, value)
            user.updated_at = self.clock.now()
            await session.flush()
        return user

    @staticmethod
    def _conflict(exc, constraint):
        if (
            getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
            == constraint
        ):
            raise ApplicationError(
                code="resource_conflict",
                message="A resource already uses these identifying values.",
                status_code=409,
            ) from None
        raise exc
