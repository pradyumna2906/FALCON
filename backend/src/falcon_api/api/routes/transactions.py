"""Authenticated transaction and internal-transfer routes."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from falcon_api.api.routes.auth import (
    CurrentPrincipalDependency,
    DatabaseSession,
)
from falcon_api.schemas.errors import ErrorResponse
from falcon_api.schemas.transaction import (
    ManualTransactionCreateRequest,
    ManualTransactionReplaceRequest,
    TransactionListQuery,
    TransactionPageResponse,
    TransactionResponse,
    TransferCreateRequest,
    TransferResponse,
)
from falcon_api.transactions import (
    ManualTransactionCommand,
    TransactionFilters,
    TransactionService,
    TransferCommand,
)


transaction_router = APIRouter(prefix="/transactions", tags=["transactions"])
transfer_router = APIRouter(prefix="/transfers", tags=["transactions"])


def transaction_service_from(request: Request) -> TransactionService:
    """Return the process-scoped transaction service."""
    return cast(TransactionService, request.app.state.transaction_service)


TransactionServiceDependency = Annotated[
    TransactionService,
    Depends(transaction_service_from),
]
TransactionQuery = Annotated[TransactionListQuery, Query()]

_AUTHENTICATION_ERROR = {
    "model": ErrorResponse,
    "description": "The access token is missing, invalid, or expired.",
}
_NOT_FOUND_ERROR = {
    "model": ErrorResponse,
    "description": "The requested owned ledger resource was not found.",
}
_CONFLICT_ERROR = {
    "model": ErrorResponse,
    "description": "The transaction has immutable provenance.",
}
_VALIDATION_ERROR = {
    "model": ErrorResponse,
    "description": "The request violates the transaction contract.",
}


@transaction_router.post(
    "",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_manual_transaction",
    summary="Create a manual income or expense",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _VALIDATION_ERROR,
    },
)
async def create_manual_transaction(
    payload: ManualTransactionCreateRequest,
    session: DatabaseSession,
    service: TransactionServiceDependency,
    principal: CurrentPrincipalDependency,
) -> TransactionResponse:
    """Create one manual entry owned by the authenticated principal."""
    result = await service.create_manual(
        session,
        user_id=principal.user_id,
        timezone=principal.timezone,
        command=_manual_command(payload),
    )
    return TransactionResponse.model_validate(result)


@transaction_router.get(
    "",
    response_model=TransactionPageResponse,
    operation_id="list_transactions",
    summary="List the authenticated user's transaction timeline",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _VALIDATION_ERROR,
    },
)
async def list_transactions(
    query: TransactionQuery,
    session: DatabaseSession,
    service: TransactionServiceDependency,
    principal: CurrentPrincipalDependency,
) -> TransactionPageResponse:
    """Return one filtered, cursor-paginated owned timeline page."""
    result = await service.list(
        session,
        user_id=principal.user_id,
        filters=TransactionFilters(
            account_id=query.account_id,
            category_id=query.category_id,
            transaction_type=query.transaction_type,
            status=query.status,
            date_from=query.date_from,
            date_to=query.date_to,
        ),
        cursor_token=query.cursor,
        limit=query.limit,
    )
    return TransactionPageResponse.model_validate(result)


@transaction_router.get(
    "/{transaction_id}",
    response_model=TransactionResponse,
    operation_id="get_transaction",
    summary="Return one owned transaction",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
    },
)
async def get_transaction(
    transaction_id: UUID,
    session: DatabaseSession,
    service: TransactionServiceDependency,
    principal: CurrentPrincipalDependency,
) -> TransactionResponse:
    """Return only a transaction owned by the principal."""
    result = await service.get(
        session,
        user_id=principal.user_id,
        transaction_id=transaction_id,
    )
    return TransactionResponse.model_validate(result)


@transaction_router.put(
    "/{transaction_id}",
    response_model=TransactionResponse,
    operation_id="replace_manual_transaction",
    summary="Replace one eligible manual transaction",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
        status.HTTP_409_CONFLICT: _CONFLICT_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _VALIDATION_ERROR,
    },
)
async def replace_manual_transaction(
    transaction_id: UUID,
    payload: ManualTransactionReplaceRequest,
    session: DatabaseSession,
    service: TransactionServiceDependency,
    principal: CurrentPrincipalDependency,
) -> TransactionResponse:
    """Replace mutable values while preserving trusted provenance."""
    result = await service.replace_manual(
        session,
        user_id=principal.user_id,
        timezone=principal.timezone,
        transaction_id=transaction_id,
        command=_manual_command(payload),
    )
    return TransactionResponse.model_validate(result)


@transaction_router.delete(
    "/{transaction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="delete_manual_transaction",
    summary="Delete one eligible manual transaction",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
        status.HTTP_409_CONFLICT: _CONFLICT_ERROR,
    },
)
async def delete_manual_transaction(
    transaction_id: UUID,
    session: DatabaseSession,
    service: TransactionServiceDependency,
    principal: CurrentPrincipalDependency,
) -> Response:
    """Delete an owned ordinary manual entry and return no body."""
    await service.delete_manual(
        session,
        user_id=principal.user_id,
        transaction_id=transaction_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@transfer_router.post(
    "",
    response_model=TransferResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_internal_transfer",
    summary="Create an atomic internal transfer",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _VALIDATION_ERROR,
    },
)
async def create_internal_transfer(
    payload: TransferCreateRequest,
    session: DatabaseSession,
    service: TransactionServiceDependency,
    principal: CurrentPrincipalDependency,
) -> TransferResponse:
    """Create equal debit and credit entries for two owned accounts."""
    result = await service.create_transfer(
        session,
        user_id=principal.user_id,
        timezone=principal.timezone,
        command=TransferCommand(
            source_account_id=payload.source_account_id,
            destination_account_id=payload.destination_account_id,
            amount=payload.amount,
            transaction_date=payload.transaction_date,
            description=payload.description,
        ),
    )
    return TransferResponse.model_validate(result)


def _manual_command(
    payload: ManualTransactionCreateRequest
    | ManualTransactionReplaceRequest,
) -> ManualTransactionCommand:
    return ManualTransactionCommand(
        account_id=payload.account_id,
        category_id=payload.category_id,
        transaction_type=payload.transaction_type,
        amount=payload.amount,
        transaction_date=payload.transaction_date,
        description=payload.description,
        merchant_name=payload.merchant_name,
    )
