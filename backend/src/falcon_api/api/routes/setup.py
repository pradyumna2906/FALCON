"""Authenticated frontend setup endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from falcon_api.api.routes.auth import CurrentPrincipalDependency, DatabaseSession
from falcon_api.auth.principal import AuthenticatedPrincipal
from falcon_api.core.errors import ApplicationError
from falcon_api.schemas.errors import ErrorResponse
from falcon_api.schemas.setup import (
    AccountDetailResponse,
    AccountMetadataRequest,
    BudgetListResponse,
    BudgetRequest,
    BudgetResponse,
    ImportHistoryResponse,
    LiabilityRequest,
    LiabilityResponse,
    PreferencesRequest,
)
from falcon_api.setup.service import SetupService


def setup_service_from():
    return SetupService()


def verified_principal(principal: CurrentPrincipalDependency):
    if principal.email_verified_at is None:
        raise ApplicationError(
            code="email_verification_required",
            message="Verify your email to continue.",
            status_code=403,
        )
    return principal


Owner = Annotated[AuthenticatedPrincipal, Depends(verified_principal)]
Service = Annotated[SetupService, Depends(setup_service_from)]
PageLimit = Annotated[int, Query(ge=1, le=100)]
PageOffset = Annotated[int, Query(ge=0, le=10000)]
setup_router = APIRouter(
    tags=["financial-setup"],
    responses={
        status: {"model": ErrorResponse} for status in (401, 403, 404, 409, 422)
    },
)


@setup_router.get(
    "/accounts/{account_id}",
    response_model=AccountDetailResponse,
    operation_id="get_account_detail",
)
async def account_detail(
    account_id: UUID, session: DatabaseSession, principal: Owner, service: Service
):
    return await service.get_account(session, principal.user_id, account_id)


@setup_router.put(
    "/accounts/{account_id}",
    response_model=AccountDetailResponse,
    operation_id="replace_account_metadata",
)
async def account_metadata(
    account_id: UUID,
    payload: AccountMetadataRequest,
    session: DatabaseSession,
    principal: Owner,
    service: Service,
):
    return await service.update_account(session, principal.user_id, account_id, payload)


@setup_router.post(
    "/accounts/{account_id}/archive",
    response_model=AccountDetailResponse,
    operation_id="archive_account",
)
async def account_archive(
    account_id: UUID, session: DatabaseSession, principal: Owner, service: Service
):
    return await service.archive_account(session, principal.user_id, account_id)


@setup_router.get(
    "/accounts/{account_id}/liability",
    response_model=LiabilityResponse,
    operation_id="get_account_liability",
)
async def liability_detail(
    account_id: UUID, session: DatabaseSession, principal: Owner, service: Service
):
    return await service.get_liability(session, principal.user_id, account_id)


@setup_router.put(
    "/accounts/{account_id}/liability",
    response_model=LiabilityResponse,
    operation_id="replace_account_liability",
)
async def liability_replace(
    account_id: UUID,
    payload: LiabilityRequest,
    session: DatabaseSession,
    principal: Owner,
    service: Service,
):
    return await service.put_liability(session, principal.user_id, account_id, payload)


@setup_router.post(
    "/budgets",
    response_model=BudgetResponse,
    status_code=201,
    operation_id="create_budget",
)
async def budget_create(
    payload: BudgetRequest, session: DatabaseSession, principal: Owner, service: Service
):
    return await service.put_budget(session, principal.user_id, payload)


@setup_router.get(
    "/budgets", response_model=BudgetListResponse, operation_id="list_budgets"
)
async def budget_list(
    session: DatabaseSession,
    principal: Owner,
    service: Service,
    limit: PageLimit = 20,
    offset: PageOffset = 0,
    include_archived: bool = False,
):
    rows = await service.repository.budgets(
        session,
        principal.user_id,
        limit=limit,
        offset=offset,
        archived=include_archived,
    )
    return {"items": rows[:limit], "has_more": len(rows) > limit}


@setup_router.get(
    "/budgets/{budget_id}", response_model=BudgetResponse, operation_id="get_budget"
)
async def budget_detail(
    budget_id: UUID, session: DatabaseSession, principal: Owner, service: Service
):
    return await service.get_budget(session, principal.user_id, budget_id)


@setup_router.put(
    "/budgets/{budget_id}", response_model=BudgetResponse, operation_id="replace_budget"
)
async def budget_replace(
    budget_id: UUID,
    payload: BudgetRequest,
    session: DatabaseSession,
    principal: Owner,
    service: Service,
):
    return await service.put_budget(session, principal.user_id, payload, budget_id)


@setup_router.delete(
    "/budgets/{budget_id}",
    status_code=204,
    operation_id="archive_budget",
    summary="Archive a budget without deleting its history",
)
async def budget_archive(
    budget_id: UUID, session: DatabaseSession, principal: Owner, service: Service
):
    await service.archive_budget(session, principal.user_id, budget_id)
    return Response(status_code=204)


@setup_router.get(
    "/preferences", response_model=PreferencesRequest, operation_id="get_preferences"
)
async def preferences_get(session: DatabaseSession, principal: Owner, service: Service):
    return await service.preferences(session, principal.user_id)


@setup_router.put(
    "/preferences",
    response_model=PreferencesRequest,
    operation_id="replace_preferences",
)
async def preferences_put(
    payload: PreferencesRequest,
    session: DatabaseSession,
    principal: Owner,
    service: Service,
):
    return await service.preferences(session, principal.user_id, payload)


@setup_router.get(
    "/imports", response_model=ImportHistoryResponse, operation_id="list_import_history"
)
async def imports_list(
    session: DatabaseSession,
    principal: Owner,
    service: Service,
    limit: PageLimit = 20,
    offset: PageOffset = 0,
):
    rows = await service.repository.imports(
        session, principal.user_id, limit=limit, offset=offset
    )
    return {"items": rows[:limit], "has_more": len(rows) > limit}
