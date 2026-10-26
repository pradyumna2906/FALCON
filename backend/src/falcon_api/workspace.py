"""Owner-only, bounded downloads and persisted notification lifecycle."""

import asyncio
import csv
import io
import json
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from falcon_api.core.errors import ApplicationError
from falcon_api.infrastructure.persistence import model_metadata, utc_now
from falcon_api.models import Notification, NotificationPreference, User, UserCredential

MAX_EXPORT_ROWS = 100_000
MAX_EXPORT_BYTES = 32 * 1024 * 1024
EXCLUDED_EXPORT_TABLES = frozenset({
    "user_credentials", "refresh_tokens", "authentication_challenges",
    "authentication_delivery_outbox", "assistant_conversation_turns",
})


def unavailable(code="workspace_resource_not_found", status=404):
    return ApplicationError(code=code, message="The requested operation could not be completed.", status_code=status)


async def reauthenticate(session, principal, payload, cryptography):
    # Serialize sensitive actions with user lifecycle operations. Passwords are
    # request-local SecretStr values and never saved in reports or event records.
    row = (await session.execute(select(UserCredential).join(User).where(
        User.id == principal.user_id,
    ).with_for_update())).scalar_one_or_none()
    if row is None or not await asyncio.to_thread(
        cryptography.passwords.verify_password,
        payload.password.get_secret_value(), row.password_hash,
    ):
        raise unavailable("reauthentication_failed", 403)


async def preferences(session, owner, payload=None):
    # Upsert avoids first-use races; defaults do not overwrite an opt-out.
    now = utc_now()
    await session.execute(insert(NotificationPreference).values(
        id=uuid4(), user_id=owner, in_app_enabled=True, created_at=now, updated_at=now,
    ).on_conflict_do_nothing(index_elements=["user_id"]))
    row = (await session.execute(select(NotificationPreference).where(
        NotificationPreference.user_id == owner,
    ).with_for_update())).scalar_one()
    if payload is not None:
        row.in_app_enabled = payload.in_app_enabled
        row.updated_at = now
        await session.flush()
    return row


async def notify(session, owner, key, title, detail):
    if not (await preferences(session, owner)).in_app_enabled:
        return
    now = utc_now()
    await session.execute(insert(Notification).values(
        id=uuid4(), user_id=owner, source_key=key, title=title, detail=detail,
        created_at=now, updated_at=now,
    ).on_conflict_do_nothing(constraint="uq_notifications_owner_source"))


def csv_cell(value):
    """Prevent spreadsheet formula injection, including leading control space."""
    text = "" if value is None else str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def transaction_csv(rows, currency):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["id", "date", "type", "amount", "currency", "description", "merchant", "status"])
    for row in rows:
        writer.writerow([csv_cell(v) for v in (
            row.id, row.transaction_date, row.transaction_type, row.amount,
            currency, row.description, row.merchant_name, row.status,
        )])
    return output.getvalue().encode("utf-8-sig")


def monthly_pdf(report):
    """One-page exact-value cash-flow report; no client financial calculations."""
    context, metrics = report.context, report.metrics
    lines = [
        "FALCON - Monthly financial report", "",
        f"Period: {context.period.date_from} to {context.period.date_to}",
        f"Currency: {context.currency}",
        f"Calculated: {context.freshness.calculated_at.isoformat()}",
        f"Eligible transactions: {context.completeness.eligible_transaction_count}",
        f"Data confidence: {context.completeness.data_confidence}", "",
        f"Gross income: {metrics.gross_income.value}",
        f"Total expense: {metrics.total_expense.value}",
        f"Net cash flow: {metrics.net_cash_flow.value}",
        f"Savings amount: {metrics.savings_amount.value}", "",
        "Only eligible posted records in the selected currency are summarized.",
        "Transfers, adjustments and other currencies are excluded.",
        "Missing or incomplete records limit this report; figures are not forecasts.",
    ]
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
    stream = DecodedStreamObject()
    escaped = [line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)') for line in lines]
    stream.set_data(('BT /F1 11 Tf 48 790 Td 20 TL ' + ' '.join(f'({line}) Tj T*' for line in escaped) + ' ET').encode('ascii'))
    page[NameObject('/Contents')] = stream
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def json_value(value):
    if isinstance(value, (Decimal, UUID)):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError("Unsupported export value")


async def export_document(session, owner, history):
    """Export owned rows, with secrets excluded and assistant text decrypted.

    Every table query has an owner predicate; there is no caller-selected table
    or owner. Oversized exports fail explicitly rather than silently truncating.
    """
    document = {"schema_version": "1", "exported_at": utc_now(), "tables": {}}
    count = 0
    for table in model_metadata().sorted_tables:
        if table.name in EXCLUDED_EXPORT_TABLES:
            continue
        if table.name == "users":
            predicate = table.c.id == owner
        elif "user_id" in table.c:
            predicate = table.c.user_id == owner
        else:
            continue
        rows = (await session.execute(select(table).where(predicate).order_by(table.c.id).limit(MAX_EXPORT_ROWS - count + 1))).mappings().all()
        count += len(rows)
        if count > MAX_EXPORT_ROWS:
            raise unavailable("export_capacity_exceeded", 413)
        document["tables"][table.name] = [dict(row) for row in rows]
    turns = await history.export_turns(session, user_id=owner, limit=MAX_EXPORT_ROWS - count + 1)
    if count + len(turns) > MAX_EXPORT_ROWS:
        raise unavailable("export_capacity_exceeded", 413)
    document["tables"]["assistant_conversation_turns"] = turns
    content = json.dumps(document, default=json_value, ensure_ascii=False).encode("utf-8")
    if len(content) > MAX_EXPORT_BYTES:
        raise unavailable("export_capacity_exceeded", 413)
    return content
