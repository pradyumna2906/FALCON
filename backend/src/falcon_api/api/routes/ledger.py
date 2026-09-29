"""Authenticated account provisioning and category discovery routes."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, status

from falcon_api.api.routes.auth import CurrentPrincipalDependency, DatabaseSession
from falcon_api.ledger import AccountCreateCommand, LedgerService
from falcon_api.schemas.errors import ErrorResponse
from falcon_api.schemas.ledger import (
    AccountCreateRequest,
    AccountListResponse,
    AccountResponse,
    CategoryListResponse,
)


account_router = APIRouter(prefix="/accounts", tags=["accounts"])
category_router = APIRouter(prefix="/categories", tags=["categories"])


def ledger_service_from(request: Request) -> LedgerService:
    """Return the process-scoped ledger setup service."""
    return cast(LedgerService, request.app.state.ledger_service)


LedgerServiceDependency = Annotated[
    LedgerService,
    Depends(ledger_service_from),
]

_AUTHENTICATION_ERROR = {
    "model": ErrorResponse,
    "description": "The access token is missing, invalid, or expired.",
}
_CONFLICT_ERROR = {
    "model": ErrorResponse,
    "description": "An account with that name already exists.",
}
_VALIDATION_ERROR = {
    "model": ErrorResponse,
    "description": "The request violates the account contract.",
}


@account_router.post(
    "",
    response_model=AccountResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_account",
    summary="Provision an account for transaction entry",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_409_CONFLICT: _CONFLICT_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _VALIDATION_ERROR,
    },
)
async def create_account(
    payload: AccountCreateRequest,
    session: DatabaseSession,
    service: LedgerServiceDependency,
    principal: CurrentPrincipalDependency,
) -> AccountResponse:
    """Create one account owned by the authenticated principal."""
    account = await service.create_account(
        session,
        user_id=principal.user_id,
        default_currency=principal.default_currency,
        command=AccountCreateCommand(
            name=payload.name,
            account_type=payload.account_type,
            institution_name=payload.institution_name,
            masked_reference=payload.masked_reference,
            currency=payload.currency,
            opening_balance=payload.opening_balance,
            opening_balance_date=payload.opening_balance_date,
        ),
    )
    return AccountResponse.model_validate(account)


@account_router.get(
    "",
    response_model=AccountListResponse,
    operation_id="list_accounts",
    summary="List active accounts owned by the authenticated user",
    responses={status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR},
)
async def list_accounts(
    session: DatabaseSession,
    service: LedgerServiceDependency,
    principal: CurrentPrincipalDependency,
) -> AccountListResponse:
    """Return active accounts without exposing the ownership key."""
    accounts = await service.list_accounts(session, user_id=principal.user_id)
    return AccountListResponse.model_validate({"items": accounts})


@category_router.get(
    "",
    response_model=CategoryListResponse,
    operation_id="list_categories",
    summary="List categories available to the authenticated user",
    responses={status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR},
)
async def list_categories(
    session: DatabaseSession,
    service: LedgerServiceDependency,
    principal: CurrentPrincipalDependency,
) -> CategoryListResponse:
    """Return active system and same-user private categories."""
    categories = await service.list_categories(
        session,
        user_id=principal.user_id,
    )
    return CategoryListResponse.model_validate({"items": categories})
