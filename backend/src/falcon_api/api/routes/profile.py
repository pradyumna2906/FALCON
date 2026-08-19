"""Authenticated financial-profile routes."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, Response, status

from falcon_api.api.routes.auth import (
    CurrentPrincipalDependency,
    DatabaseSession,
)
from falcon_api.profile import (
    FinancialProfileCommand,
    FinancialProfileService,
)
from falcon_api.schemas.errors import ErrorResponse
from falcon_api.schemas.profile import (
    FinancialProfilePutRequest,
    FinancialProfileResponse,
)


profile_router = APIRouter(
    prefix="/profile",
    tags=["financial-profile"],
)


def financial_profile_service_from(
    request: Request,
) -> FinancialProfileService:
    """Return the process-scoped financial-profile service."""
    return cast(
        FinancialProfileService,
        request.app.state.financial_profile_service,
    )


FinancialProfileServiceDependency = Annotated[
    FinancialProfileService,
    Depends(financial_profile_service_from),
]

_AUTHENTICATION_ERROR = {
    "model": ErrorResponse,
    "description": "The access token is missing, invalid, or expired.",
}
_NOT_FOUND_ERROR = {
    "model": ErrorResponse,
    "description": "The authenticated user has no financial profile.",
}
_VALIDATION_ERROR = {
    "model": ErrorResponse,
    "description": "The request violates the profile contract.",
}


@profile_router.get(
    "",
    response_model=FinancialProfileResponse,
    status_code=status.HTTP_200_OK,
    operation_id="get_financial_profile",
    summary="Return the authenticated user's financial profile",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
    },
)
async def get_financial_profile(
    session: DatabaseSession,
    service: FinancialProfileServiceDependency,
    principal: CurrentPrincipalDependency,
) -> FinancialProfileResponse:
    """Return only the profile owned by the authenticated principal."""
    profile = await service.get(
        session,
        user_id=principal.user_id,
    )
    return FinancialProfileResponse.model_validate(profile)


@profile_router.put(
    "",
    response_model=FinancialProfileResponse,
    status_code=status.HTTP_200_OK,
    operation_id="put_financial_profile",
    summary="Create or replace the authenticated user's financial profile",
    responses={
        status.HTTP_201_CREATED: {
            "model": FinancialProfileResponse,
            "description": "The financial profile was created.",
        },
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _VALIDATION_ERROR,
    },
)
async def put_financial_profile(
    payload: FinancialProfilePutRequest,
    response: Response,
    session: DatabaseSession,
    service: FinancialProfileServiceDependency,
    principal: CurrentPrincipalDependency,
) -> FinancialProfileResponse:
    """Create or idempotently replace the principal's profile."""
    result = await service.put(
        session,
        user_id=principal.user_id,
        command=FinancialProfileCommand(
            income_pattern=payload.income_pattern,
            income_stability=payload.income_stability,
            has_household_responsibilities=(
                payload.has_household_responsibilities
            ),
            dependant_count=payload.dependant_count,
            emergency_fund_target_months=(
                payload.emergency_fund_target_months
            ),
        ),
    )

    if result.created:
        response.status_code = status.HTTP_201_CREATED

    return FinancialProfileResponse.model_validate(result.profile)
