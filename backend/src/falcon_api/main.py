"""FastAPI application composition root."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from falcon_api import __version__
from falcon_api.api.errors import register_exception_handlers
from falcon_api.api.router import api_v1_router
from falcon_api.api.routes.health import health_router
from falcon_api.auth.login import LoginService
from falcon_api.auth.password_recovery import PasswordRecoveryService
from falcon_api.auth.principal import CurrentPrincipalService
from falcon_api.auth.registration import RegistrationService
from falcon_api.auth.services import create_authentication_cryptography
from falcon_api.auth.session_lifecycle import SessionLifecycleService
from falcon_api.core.config import Settings, get_settings
from falcon_api.core.logging import configure_logging
from falcon_api.core.request_context import REQUEST_ID_HEADER
from falcon_api.infrastructure.database import (
    DatabaseResources,
    create_database_resources,
)
from falcon_api.imports import ImportService
from falcon_api.ledger import LedgerService
from falcon_api.middleware.request_context import RequestContextMiddleware
from falcon_api.profile import FinancialProfileService
from falcon_api.transactions import TransactionCursorCodec, TransactionService


_CORS_ALLOWED_METHODS = ("DELETE", "GET", "POST", "PUT")
_CORS_ALLOWED_HEADERS = (
    "Accept",
    "Authorization",
    "Content-Type",
    REQUEST_ID_HEADER,
)
DatabaseFactory = Callable[[Settings], DatabaseResources]


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Create and reliably dispose process-scoped resources."""
    database_factory: DatabaseFactory = application.state.database_factory
    database = database_factory(application.state.settings)
    application.state.database = database

    try:
        yield
    finally:
        await database.dispose()


def create_app(
    settings: Settings | None = None,
    *,
    database_factory: DatabaseFactory = create_database_resources,
) -> FastAPI:
    """Build an isolated FastAPI application instance."""
    app_settings = settings or get_settings()
    docs_enabled = app_settings.api_docs_enabled
    configure_logging()

    application = FastAPI(
        title=app_settings.app_name,
        version=__version__,
        debug=app_settings.debug,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
    )
    application.state.settings = app_settings
    application.state.database_factory = database_factory
    application.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=_CORS_ALLOWED_METHODS,
        allow_headers=_CORS_ALLOWED_HEADERS,
        expose_headers=(REQUEST_ID_HEADER,),
    )

    authentication_cryptography = create_authentication_cryptography(
        app_settings,
    )
    application.state.authentication_cryptography = (
        authentication_cryptography
    )
    application.state.registration_service = RegistrationService(
        cryptography=authentication_cryptography,
        verification_lifetime=timedelta(
            minutes=(
                app_settings.auth_email_verification_lifetime_minutes
            )
        ),
    )
    application.state.login_service = LoginService(
        cryptography=authentication_cryptography,
        refresh_lifetime=timedelta(
            days=app_settings.auth_refresh_token_lifetime_days,
        ),
    )
    application.state.current_principal_service = (
        CurrentPrincipalService(
            access_tokens=authentication_cryptography.access_tokens,
        )
    )
    application.state.password_recovery_service = (
        PasswordRecoveryService(
            cryptography=authentication_cryptography,
            reset_lifetime=timedelta(
                minutes=(
                    app_settings.auth_password_reset_lifetime_minutes
                ),
            ),
        )
    )
    application.state.session_lifecycle_service = (
        SessionLifecycleService(
            cryptography=authentication_cryptography,
        )
    )
    application.state.financial_profile_service = (
        FinancialProfileService()
    )
    application.state.ledger_service = LedgerService()
    application.state.transaction_service = TransactionService(
        cursor_codec=TransactionCursorCodec(
            signing_secret=(
                app_settings.auth_signing_secret.get_secret_value()
            ),
        )
    )
    application.state.import_service = ImportService()

    application.add_middleware(RequestContextMiddleware)
    register_exception_handlers(application)
    application.include_router(health_router)
    application.include_router(api_v1_router)
    return application


app = create_app()
