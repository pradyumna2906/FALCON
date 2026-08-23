"""Authenticated single and bounded-batch classification routes."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from falcon_api.api.routes.auth import (
    CurrentPrincipalDependency,
    DatabaseSession,
)
from falcon_api.classification.application import (
    TransactionClassificationService,
)
from falcon_api.schemas.classification import (
    ClassificationBatchRequest,
    ClassificationBatchResponse,
    ClassificationResult,
)
from falcon_api.schemas.errors import ErrorResponse


classification_router = APIRouter(tags=["classification"])


def classification_service_from(
    request: Request,
) -> TransactionClassificationService:
    """Return the process-scoped transaction-classification service."""
    return cast(
        TransactionClassificationService,
        request.app.state.classification_service,
    )


ClassificationServiceDependency = Annotated[
    TransactionClassificationService,
    Depends(classification_service_from),
]

_AUTHENTICATION_ERROR = {
    "model": ErrorResponse,
    "description": "The access token is missing, invalid, or expired.",
}
_NOT_FOUND_ERROR = {
    "model": ErrorResponse,
    "description": "An owned transaction or required category was not found.",
}
_CONFLICT_ERROR = {
    "model": ErrorResponse,
    "description": "A protected or changed classification cannot be replaced.",
}
_CLASSIFICATION_ERROR = {
    "model": ErrorResponse,
    "description": "The target or active classifier is unavailable.",
}


@classification_router.post(
    "/transactions/{transaction_id}/classification",
    response_model=ClassificationResult,
    operation_id="classify_transaction",
    summary="Classify one owned transaction",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
        status.HTTP_409_CONFLICT: _CONFLICT_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _CLASSIFICATION_ERROR,
    },
)
async def classify_transaction(
    transaction_id: UUID,
    session: DatabaseSession,
    service: ClassificationServiceDependency,
    principal: CurrentPrincipalDependency,
) -> ClassificationResult:
    """Classify one transaction selected under the authenticated owner."""
    return await service.classify_one(
        session,
        user_id=principal.user_id,
        transaction_id=transaction_id,
    )


@classification_router.post(
    "/classifications/batch",
    response_model=ClassificationBatchResponse,
    operation_id="classify_transaction_batch",
    summary="Classify up to 100 owned transactions atomically",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
        status.HTTP_409_CONFLICT: _CONFLICT_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _CLASSIFICATION_ERROR,
    },
)
async def classify_transaction_batch(
    payload: ClassificationBatchRequest,
    session: DatabaseSession,
    service: ClassificationServiceDependency,
    principal: CurrentPrincipalDependency,
) -> ClassificationBatchResponse:
    """Classify a unique owner-scoped batch and preserve request order."""
    results = await service.classify_batch(
        session,
        user_id=principal.user_id,
        transaction_ids=payload.transaction_ids,
    )
    return ClassificationBatchResponse(items=results)
