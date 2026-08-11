"""FastAPI application composition root."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from falcon_api import __version__
from falcon_api.api.errors import register_exception_handlers
from falcon_api.api.router import api_v1_router
from falcon_api.api.routes.health import health_router
from falcon_api.core.config import Settings, get_settings
from falcon_api.core.logging import configure_logging
from falcon_api.core.request_context import REQUEST_ID_HEADER
from falcon_api.middleware.request_context import RequestContextMiddleware


_CORS_ALLOWED_METHODS = ("GET",)
_CORS_ALLOWED_HEADERS = ("Accept", "Content-Type", REQUEST_ID_HEADER)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Own process-scoped resources as later checkpoints introduce them."""
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
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
    application.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=_CORS_ALLOWED_METHODS,
        allow_headers=_CORS_ALLOWED_HEADERS,
        expose_headers=(REQUEST_ID_HEADER,),
    )
    application.add_middleware(RequestContextMiddleware)
    register_exception_handlers(application)
    application.include_router(health_router)
    application.include_router(api_v1_router)
    return application


app = create_app()
