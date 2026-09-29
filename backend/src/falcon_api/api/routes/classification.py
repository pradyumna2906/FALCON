"""Authenticated single and bounded-batch classification routes."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

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
    ClassificationCorrectionResult,
    ClassificationResult,
    MerchantMemoryListQuery,
    MerchantMemoryPageResponse,
    MerchantMemoryResult,
    MerchantMemoryWriteRequest,
    TransactionCategoryCorrectionRequest,
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
MerchantMemoryQuery = Annotated[MerchantMemoryListQuery, Query()]

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


@classification_router.post(
    "/transactions/{transaction_id}/classification/correction",
    response_model=ClassificationCorrectionResult,
    status_code=status.HTTP_201_CREATED,
    operation_id="correct_transaction_classification",
    summary="Correct one stored transaction classification",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
        status.HTTP_409_CONFLICT: _CONFLICT_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _CLASSIFICATION_ERROR,
    },
)
async def correct_transaction_classification(
    transaction_id: UUID,
    payload: TransactionCategoryCorrectionRequest,
    session: DatabaseSession,
    service: ClassificationServiceDependency,
    principal: CurrentPrincipalDependency,
) -> ClassificationCorrectionResult:
    """Capture trusted prediction provenance and one reviewed category."""
    return await service.correct_category(
        session,
        user_id=principal.user_id,
        transaction_id=transaction_id,
        category_id=payload.category_id,
    )


@classification_router.put(
    "/classification/merchant-memories",
    response_model=MerchantMemoryResult,
    operation_id="set_merchant_memory",
    summary="Create or replace an exact personal merchant mapping",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _CLASSIFICATION_ERROR,
    },
)
async def set_merchant_memory(
    payload: MerchantMemoryWriteRequest,
    session: DatabaseSession,
    service: ClassificationServiceDependency,
    principal: CurrentPrincipalDependency,
) -> MerchantMemoryResult:
    """Upsert one owner-isolated exact mapping without retraining a model."""
    return await service.set_merchant_memory(
        session,
        user_id=principal.user_id,
        merchant_name=payload.merchant_name,
        category_id=payload.category_id,
    )


@classification_router.get(
    "/classification/merchant-memories",
    response_model=MerchantMemoryPageResponse,
    operation_id="list_merchant_memories",
    summary="List personal merchant mappings",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _CLASSIFICATION_ERROR,
    },
)
async def list_merchant_memories(
    query: MerchantMemoryQuery,
    session: DatabaseSession,
    service: ClassificationServiceDependency,
    principal: CurrentPrincipalDependency,
) -> MerchantMemoryPageResponse:
    """Return one bounded mapping page in stable merchant order."""
    return await service.list_merchant_memories(
        session,
        user_id=principal.user_id,
        after=query.cursor,
        limit=query.limit,
    )


@classification_router.delete(
    "/classification/merchant-memories/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="delete_merchant_memory",
    summary="Delete one personal merchant mapping",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
    },
)
async def delete_merchant_memory(
    memory_id: UUID,
    session: DatabaseSession,
    service: ClassificationServiceDependency,
    principal: CurrentPrincipalDependency,
) -> Response:
    """Remove one mapping under the authenticated owner predicate."""
    await service.delete_merchant_memory(
        session,
        user_id=principal.user_id,
        memory_id=memory_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
