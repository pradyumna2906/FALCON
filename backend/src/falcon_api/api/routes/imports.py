"""Authenticated statement upload and reconciliation routes."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError

from falcon_api.api.routes.auth import (
    CurrentPrincipalDependency,
    DatabaseSession,
)
from falcon_api.imports import ImportService, StatementImportCommand
from falcon_api.imports.extraction import read_bounded_upload
from falcon_api.models.enums import ImportDateOrder, ImportSourceType
from falcon_api.schemas.errors import ErrorResponse
from falcon_api.schemas.imports import ImportJobResponse, StatementImportOptions
from pydantic import ValidationError


import_router = APIRouter(prefix="/imports", tags=["imports"])


def import_service_from(request: Request) -> ImportService:
    """Return the process-scoped statement import service."""
    return cast(ImportService, request.app.state.import_service)


ImportServiceDependency = Annotated[
    ImportService,
    Depends(import_service_from),
]

_AUTHENTICATION_ERROR = {
    "model": ErrorResponse,
    "description": "The access token is missing, invalid, or expired.",
}
_NOT_FOUND_ERROR = {
    "model": ErrorResponse,
    "description": "The requested owned import resource was not found.",
}
_CONFLICT_ERROR = {
    "model": ErrorResponse,
    "description": "The same statement file was already imported.",
}
_TOO_LARGE_ERROR = {
    "model": ErrorResponse,
    "description": "The statement exceeds the supported upload limit.",
}
_UNSUPPORTED_ERROR = {
    "model": ErrorResponse,
    "description": "The statement file format is unsupported.",
}
_VALIDATION_ERROR = {
    "model": ErrorResponse,
    "description": "The import metadata or statement mapping is invalid.",
}
_IMPORT_FORM_FIELDS = frozenset({
    "file",
    "account_id",
    "source_type",
    "date_order",
    "header_row",
    "sheet_name",
    "file_password",
})


@import_router.post(
    "",
    response_model=ImportJobResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="import_statement",
    summary="Import a CSV, Excel, or digital PDF statement",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
        status.HTTP_409_CONFLICT: _CONFLICT_ERROR,
        status.HTTP_413_CONTENT_TOO_LARGE: _TOO_LARGE_ERROR,
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: _UNSUPPORTED_ERROR,
        status.HTTP_422_UNPROCESSABLE_CONTENT: _VALIDATION_ERROR,
    },
)
async def import_statement(
    request: Request,
    file: Annotated[UploadFile, File(description="CSV, XLSX, or digital PDF statement")],
    account_id: Annotated[UUID, Form()],
    source_type: Annotated[ImportSourceType, Form()],
    session: DatabaseSession,
    service: ImportServiceDependency,
    principal: CurrentPrincipalDependency,
    date_order: Annotated[ImportDateOrder, Form()] = ImportDateOrder.DAY_FIRST,
    header_row: Annotated[int, Form(ge=1, le=50)] = 1,
    sheet_name: Annotated[str | None, Form(max_length=31)] = None,
    file_password: Annotated[
        str | None,
        Form(min_length=1, max_length=128, description="Ephemeral PDF password"),
    ] = None,
) -> ImportJobResponse:
    """Load one bounded statement into the authenticated user's ledger."""
    form = await request.form()
    unexpected = set(form) - _IMPORT_FORM_FIELDS
    repeated = {
        field
        for field in _IMPORT_FORM_FIELDS
        if len(form.getlist(field)) > 1
    }
    if unexpected or repeated:
        fields = sorted(unexpected | repeated)
        raise RequestValidationError([
            {
                "type": "extra_forbidden",
                "loc": ("body", field),
                "msg": "Unexpected or repeated field.",
                "input": None,
            }
            for field in fields
        ])

    try:
        options = StatementImportOptions(
            account_id=account_id,
            source_type=source_type,
            date_order=date_order,
            header_row=header_row,
            sheet_name=sheet_name,
        )
    except ValidationError as exc:
        errors = [
            {**error, "loc": ("body", *error["loc"])}
            for error in exc.errors()
        ]
        raise RequestValidationError(errors) from None

    try:
        content = await read_bounded_upload(file)
    finally:
        await file.close()
    result = await service.process(
        session,
        user_id=principal.user_id,
        timezone=principal.timezone,
        command=StatementImportCommand(
            filename=file.filename or "",
            content_type=file.content_type or "",
            content=content,
            options=options,
            file_password=file_password,
        ),
    )
    return ImportJobResponse.model_validate(result)


@import_router.get(
    "/{job_id}",
    response_model=ImportJobResponse,
    operation_id="get_import_job",
    summary="Return one owned import reconciliation result",
    responses={
        status.HTTP_401_UNAUTHORIZED: _AUTHENTICATION_ERROR,
        status.HTTP_404_NOT_FOUND: _NOT_FOUND_ERROR,
    },
)
async def get_import_job(
    job_id: UUID,
    session: DatabaseSession,
    service: ImportServiceDependency,
    principal: CurrentPrincipalDependency,
) -> ImportJobResponse:
    """Return only an import job owned by the authenticated principal."""
    result = await service.get_job(
        session,
        user_id=principal.user_id,
        job_id=job_id,
    )
    return ImportJobResponse.model_validate(result)
