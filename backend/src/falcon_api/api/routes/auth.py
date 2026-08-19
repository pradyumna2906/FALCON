"""Registration, verification, login, and session-lifecycle routes."""

from typing import Annotated, Final, cast

from fastapi import (
    APIRouter,
    Depends,
    Request,
    Response,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from falcon_api.auth.login import LoginCommand, LoginService
from falcon_api.auth.registration import (
    RegistrationCommand,
    RegistrationService,
)
from falcon_api.auth.session_lifecycle import SessionLifecycleService
from falcon_api.core.config import AppEnvironment, Settings
from falcon_api.core.errors import ApplicationError
from falcon_api.infrastructure.database import get_database_session
from falcon_api.schemas.auth import (
    EmailVerificationConfirmation,
    EmailVerificationRequest,
    GenericAcceptedResponse,
    LoginRequest,
    LoginResponse,
    RegisteredUserResponse,
    RegistrationRequest,
)


_REFRESH_COOKIE_NAME: Final = "falcon_refresh_token"
_REFRESH_COOKIE_PATH: Final = "/api/v1/auth"

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


def login_service_from(request: Request) -> LoginService:
    """Return the process-scoped login service."""
    return cast(
        LoginService,
        request.app.state.login_service,
    )


def session_lifecycle_service_from(
    request: Request,
) -> SessionLifecycleService:
    """Return the process-scoped refresh-session service."""
    return cast(
        SessionLifecycleService,
        request.app.state.session_lifecycle_service,
    )


def settings_from(request: Request) -> Settings:
    """Return the application's validated settings."""
    return cast(Settings, request.app.state.settings)


RegistrationServiceDependency = Annotated[
    RegistrationService,
    Depends(registration_service_from),
]
LoginServiceDependency = Annotated[
    LoginService,
    Depends(login_service_from),
]
SessionLifecycleServiceDependency = Annotated[
    SessionLifecycleService,
    Depends(session_lifecycle_service_from),
]
SettingsDependency = Annotated[
    Settings,
    Depends(settings_from),
]


def _set_refresh_cookie(
    response: Response,
    *,
    token: str,
    expires_at,
    settings: Settings,
) -> None:
    """Set the narrowly scoped protected refresh cookie."""
    response.set_cookie(
        key=_REFRESH_COOKIE_NAME,
        value=token,
        max_age=settings.auth_refresh_token_lifetime_days * 86_400,
        expires=expires_at,
        path=_REFRESH_COOKIE_PATH,
        secure=settings.env is not AppEnvironment.DEVELOPMENT,
        httponly=True,
        samesite="lax",
    )


def _clear_refresh_cookie(
    response: Response,
    *,
    settings: Settings,
) -> None:
    """Expire the protected refresh cookie with matching attributes."""
    response.delete_cookie(
        key=_REFRESH_COOKIE_NAME,
        path=_REFRESH_COOKIE_PATH,
        secure=settings.env is not AppEnvironment.DEVELOPMENT,
        httponly=True,
        samesite="lax",
    )


def _require_trusted_origin(
    request: Request,
    *,
    settings: Settings,
) -> None:
    """Reject an explicitly supplied untrusted browser origin."""
    origin = request.headers.get("origin")

    if origin is None:
        return

    if origin not in settings.cors_allowed_origins:
        raise ApplicationError(
            code="origin_not_allowed",
            message="The request origin is not allowed.",
            status_code=403,
        )


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
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    operation_id="login_user",
    summary="Authenticate and create a refresh session",
)
async def login_user(
    request: LoginRequest,
    response: Response,
    session: DatabaseSession,
    service: LoginServiceDependency,
    settings: SettingsDependency,
) -> LoginResponse:
    """Issue a short-lived access token and protected refresh cookie."""
    result = await service.login(
        session,
        LoginCommand(
            email=request.email,
            password=request.password,
        ),
    )
    _set_refresh_cookie(
        response,
        token=result.refresh_token,
        expires_at=result.refresh_token_expires_at,
        settings=settings,
    )

    return LoginResponse(
        access_token=result.access_token,
        expires_at=result.access_token_expires_at,
    )


@auth_router.post(
    "/refresh",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    operation_id="refresh_session",
    summary="Rotate the refresh token and issue access",
)
async def refresh_session(
    request: Request,
    response: Response,
    session: DatabaseSession,
    service: SessionLifecycleServiceDependency,
    settings: SettingsDependency,
) -> LoginResponse:
    """Rotate one valid refresh credential exactly once."""
    _require_trusted_origin(request, settings=settings)
    raw_token = request.cookies.get(_REFRESH_COOKIE_NAME)

    if raw_token is None:
        raise ApplicationError(
            code="invalid_refresh_session",
            message="The refresh session is invalid or expired.",
            status_code=401,
        )

    result = await service.refresh(
        session,
        token=raw_token,
    )
    _set_refresh_cookie(
        response,
        token=result.refresh_token,
        expires_at=result.refresh_token_expires_at,
        settings=settings,
    )

    return LoginResponse(
        access_token=result.access_token,
        expires_at=result.access_token_expires_at,
    )


@auth_router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="logout_session",
    summary="Revoke the current refresh session",
)
async def logout_session(
    request: Request,
    response: Response,
    session: DatabaseSession,
    service: SessionLifecycleServiceDependency,
    settings: SettingsDependency,
) -> Response:
    """Revoke a resolvable session and always clear the cookie."""
    _require_trusted_origin(request, settings=settings)
    await service.logout(
        session,
        token=request.cookies.get(_REFRESH_COOKIE_NAME),
    )
    _clear_refresh_cookie(response, settings=settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


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
