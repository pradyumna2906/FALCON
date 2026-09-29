"""Verified owner reports, notification inbox, sessions and privacy actions."""

from calendar import monthrange
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import delete, select

from falcon_api.analytics.application import AnalyticsSelection
from falcon_api.analytics.semantics import AnalyticsComparisonMode
from falcon_api.core.errors import ApplicationError
from falcon_api.api.routes.analytics import AnalyticsServiceDependency
from falcon_api.api.routes.assistant import AssistantHistoryDependency
from falcon_api.api.routes.auth import DatabaseSession
from falcon_api.api.routes.setup import Owner, PageLimit, PageOffset
from falcon_api.infrastructure.persistence import utc_now
from falcon_api.models import Account, Notification, RefreshSession, Transaction, User
from falcon_api.schemas.analytics import AnalyticsGranularity
from falcon_api.schemas.errors import ErrorResponse
from falcon_api.schemas.workspace import (
    ErasureRequest, NotificationList, NotificationPreferences, NotificationResponse,
    ReauthenticationRequest, SessionList, SessionResponse,
)
from falcon_api.workspace import (
    MAX_EXPORT_BYTES, MAX_EXPORT_ROWS, export_document, monthly_pdf, notify,
    preferences, reauthenticate, transaction_csv, unavailable,
)

workspace_router = APIRouter(tags=["workspace"], responses={
    code: {"model": ErrorResponse} for code in (401, 403, 404, 413, 422, 429)
})
CurrencyQuery = Annotated[str, Query(pattern=r"^[A-Z]{3}$")]
MonthQuery = Annotated[str, Query(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")]


async def sensitive_permit(request: Request, principal: Owner):
    """Use a dedicated bounded limiter for password checks and large exports."""
    try:
        async with request.app.state.workspace_limiter.permit(principal.user_id):
            yield
    except ApplicationError as exc:
        if exc.status_code == 429:
            raise unavailable("workspace_rate_limited", 429) from None
        raise


def download(content, filename, media_type):
    return Response(content=content, media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })


def month_dates(month):
    try:
        start = date.fromisoformat(month + "-01")
    except ValueError:
        raise unavailable("invalid_report_month", 422) from None
    return start, start.replace(day=monthrange(start.year, start.month)[1])


@workspace_router.get("/reports/monthly.pdf", operation_id="download_monthly_report", response_class=Response,
    responses={200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}}})
async def report_pdf(month: MonthQuery, currency: CurrencyQuery, session: DatabaseSession, principal: Owner, service: AnalyticsServiceDependency):
    start, end = month_dates(month)
    report = await service.cash_flow(session, user_id=principal.user_id,
        trusted_timezone=principal.timezone, default_currency=principal.default_currency,
        selection=AnalyticsSelection(date_from=start, date_to=end, currency=currency, comparison=AnalyticsComparisonMode.NONE),
        granularity=AnalyticsGranularity.MONTH)
    return download(monthly_pdf(report), f"falcon-{month}-{currency}.pdf", "application/pdf")


@workspace_router.get("/reports/transactions.csv", operation_id="download_transactions_csv", response_class=Response,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}}}})
async def report_csv(month: MonthQuery, currency: CurrencyQuery, session: DatabaseSession, principal: Owner):
    start, end = month_dates(month)
    rows = (await session.scalars(select(Transaction).join(Account, Transaction.account_id == Account.id).where(
        Transaction.user_id == principal.user_id, Account.user_id == principal.user_id,
        Account.currency == currency, Transaction.transaction_date >= start, Transaction.transaction_date <= end,
    ).order_by(Transaction.transaction_date, Transaction.id).limit(MAX_EXPORT_ROWS + 1))).all()
    if len(rows) > MAX_EXPORT_ROWS:
        raise unavailable("export_capacity_exceeded", 413)
    content = transaction_csv(rows, currency)
    if len(content) > MAX_EXPORT_BYTES:
        raise unavailable("export_capacity_exceeded", 413)
    return download(content, f"falcon-transactions-{month}-{currency}.csv", "text/csv")


@workspace_router.get("/notifications/preferences", response_model=NotificationPreferences, operation_id="get_notification_preferences")
async def notification_preferences(session: DatabaseSession, principal: Owner):
    return await preferences(session, principal.user_id)


@workspace_router.put("/notifications/preferences", response_model=NotificationPreferences, operation_id="replace_notification_preferences")
async def set_notification_preferences(payload: NotificationPreferences, session: DatabaseSession, principal: Owner):
    return await preferences(session, principal.user_id, payload)


@workspace_router.post("/notifications/sync", status_code=204, operation_id="sync_notifications")
async def sync_notifications(session: DatabaseSession, principal: Owner):
    # Generate bounded persisted events from actual owner import outcomes.
    from falcon_api.models import ImportJob
    rows = (await session.scalars(select(ImportJob).where(ImportJob.user_id == principal.user_id).order_by(ImportJob.created_at.desc()).limit(100))).all()
    for job in rows:
        await notify(session, principal.user_id, f"import:{job.id}:{job.status}", "Import status updated", f"Import {job.id}: {job.status}. Open Money to review its accepted rows and issues.")
    return Response(status_code=204)


@workspace_router.get("/notifications", response_model=NotificationList, operation_id="list_notifications")
async def notifications(session: DatabaseSession, principal: Owner, limit: PageLimit = 20, offset: PageOffset = 0):
    rows = (await session.scalars(select(Notification).where(Notification.user_id == principal.user_id, Notification.dismissed_at.is_(None)).order_by(Notification.created_at.desc(), Notification.id).offset(offset).limit(limit + 1))).all()
    return {"items": rows[:limit], "has_more": len(rows) > limit}


async def notification_row(session, owner, identifier):
    row = (await session.scalars(select(Notification).where(Notification.user_id == owner, Notification.id == identifier).with_for_update())).one_or_none()
    if row is None:
        raise unavailable()
    return row


@workspace_router.post("/notifications/{notification_id}/read", response_model=NotificationResponse, operation_id="mark_notification_read")
async def read_notification(notification_id: UUID, session: DatabaseSession, principal: Owner):
    row = await notification_row(session, principal.user_id, notification_id)
    row.read_at = row.read_at or utc_now()
    await session.flush()
    return row


@workspace_router.delete("/notifications/{notification_id}", status_code=204, operation_id="dismiss_notification")
async def dismiss_notification(notification_id: UUID, session: DatabaseSession, principal: Owner):
    row = await notification_row(session, principal.user_id, notification_id)
    row.dismissed_at = row.dismissed_at or utc_now()
    await session.flush()
    return Response(status_code=204)


@workspace_router.get("/security/sessions", response_model=SessionList, operation_id="list_security_sessions")
async def sessions(session: DatabaseSession, principal: Owner, limit: PageLimit = 20, offset: PageOffset = 0):
    rows = (await session.scalars(select(RefreshSession).where(RefreshSession.user_id == principal.user_id, RefreshSession.revoked_at.is_(None), RefreshSession.expires_at > utc_now()).order_by(RefreshSession.created_at.desc(), RefreshSession.id).offset(offset).limit(limit + 1))).all()
    return SessionList(items=tuple(SessionResponse(id=row.id, created_at=row.created_at, last_used_at=row.last_used_at, expires_at=row.expires_at, current=row.id == principal.session_id) for row in rows[:limit]), has_more=len(rows) > limit)


@workspace_router.post("/security/sessions/{session_id}/revoke", status_code=204, operation_id="revoke_security_session", dependencies=[Depends(sensitive_permit)])
async def revoke_session(session_id: UUID, payload: ReauthenticationRequest, request: Request, session: DatabaseSession, principal: Owner):
    await reauthenticate(session, principal, payload, request.app.state.authentication_cryptography)
    row = (await session.scalars(select(RefreshSession).where(RefreshSession.id == session_id, RefreshSession.user_id == principal.user_id).with_for_update())).one_or_none()
    if row is None:
        raise unavailable()
    if row.revoked_at is None:
        row.revoked_at = utc_now()
        row.revocation_reason = "user_security_action"
    await session.flush()
    return Response(status_code=204)


@workspace_router.post("/privacy/export", operation_id="export_user_data", response_class=Response, dependencies=[Depends(sensitive_permit)],
    responses={200: {"content": {"application/json": {"schema": {"type": "string", "format": "binary"}}}}})
async def export_user(payload: ReauthenticationRequest, request: Request, session: DatabaseSession, principal: Owner, history: AssistantHistoryDependency):
    await reauthenticate(session, principal, payload, request.app.state.authentication_cryptography)
    content = await export_document(session, principal.user_id, history)
    return download(content, "falcon-personal-data.json", "application/json")


@workspace_router.post("/privacy/erase", status_code=204, operation_id="erase_user_data", dependencies=[Depends(sensitive_permit)])
async def erase_user(payload: ErasureRequest, request: Request, session: DatabaseSession, principal: Owner):
    await reauthenticate(session, principal, payload, request.app.state.authentication_cryptography)
    # User-root cascade is the same lifecycle exercised by database integration.
    await session.execute(delete(User).where(User.id == principal.user_id))
    return Response(status_code=204)
