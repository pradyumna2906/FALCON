"""Registration and email-verification API routes."""

from typing import Annotated, cast

from fastapi import (
    APIRouter,
    Depends,
    Request,
    Response,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.auth.registration import (
    RegistrationCommand,
    RegistrationService,
)
from falcon_api.infrastructure.database import get_database_session
from falcon_api.schemas.auth import (
    EmailVerificationConfirmation,
    EmailVerificationRequest,
    GenericAcceptedResponse,
    RegisteredUserResponse,
    RegistrationRequest,
)


auth_router = APIRouter(
    prefix="/auth",
    tags=["authentication"],
)

DatabaseSession = Annotated[
    AsyncSession,
    Depends(get_database_session),
]


def registration_service_from(
    request: Request,
) -> RegistrationService:
    """Return the process-scoped registration service."""
    return cast(
        RegistrationService,
        request.app.state.registration_service,
    )


RegistrationServiceDependency = Annotated[
    RegistrationService,
    Depends(registration_service_from),
]


@auth_router.post(
    "/register",
    response_model=RegisteredUserResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="register_user",
    summary="Register an email and password account",
)
async def register_user(
    request: RegistrationRequest,
    session: DatabaseSession,
    service: RegistrationServiceDependency,
) -> RegisteredUserResponse:
    """Create an unverified account and queue its verification message."""
    result = await service.register(
        session,
        RegistrationCommand(
            email=request.email,
            password=request.password,
            display_name=request.display_name,
            timezone=request.timezone,
            default_currency=request.default_currency,
        ),
    )

    return RegisteredUserResponse(
        id=result.user_id,
        email=result.email,
    )


@auth_router.post(
    "/email-verification/request",
    response_model=GenericAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="request_email_verification",
    summary="Request an email-verification message",
)
async def request_email_verification(
    request: EmailVerificationRequest,
    session: DatabaseSession,
    service: RegistrationServiceDependency,
) -> GenericAcceptedResponse:
    """Queue an eligible verification message without account disclosure."""
    await service.request_email_verification(
        session,
        email=request.email,
    )

    return GenericAcceptedResponse()


@auth_router.post(
    "/email-verification/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="confirm_email_verification",
    summary="Confirm an email-verification token",
)
async def confirm_email_verification(
    request: EmailVerificationConfirmation,
    session: DatabaseSession,
    service: RegistrationServiceDependency,
) -> Response:
    """Consume a verification challenge and verify its active user."""
    await service.confirm_email_verification(
        session,
        token=request.token,
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
