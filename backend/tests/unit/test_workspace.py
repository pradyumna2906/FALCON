"""Security boundaries and exact downloadable representation tests."""

import asyncio
import csv
import io
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from pypdf import PdfReader

from falcon_api.api.routes.workspace import month_dates
from falcon_api.core.errors import ApplicationError
from falcon_api.schemas.workspace import ErasureRequest, ReauthenticationRequest
from falcon_api.workspace import csv_cell, export_document, json_value, monthly_pdf, reauthenticate, transaction_csv


@pytest.mark.parametrize("text", ["=1+1", "+SUM(A1)", "-cmd", "@SUM(A1)", " \t=1", "\r=1", "\nfoo"])
def test_csv_neutralizes_formulas(text):
    assert csv_cell(text) == "'" + text


def test_csv_preserves_exact_decimal_and_quoted_unicode():
    row = SimpleNamespace(id=uuid4(), transaction_date=date(2026, 8, 1), transaction_type="expense",
        amount=Decimal("1234.5678"), description='Café, "meal"', merchant_name="=HYPERLINK(1)", status="posted")
    content = transaction_csv([row], "INR")
    decoded = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
    assert decoded[0]["amount"] == "1234.5678"
    assert decoded[0]["description"] == row.description
    assert decoded[0]["merchant"].startswith("'=")
    assert decoded[0]["currency"] == "INR"


def test_pdf_is_readable_and_preserves_exact_metrics():
    metric = SimpleNamespace(value=Decimal("123.4567"))
    report = SimpleNamespace(context=SimpleNamespace(
        period=SimpleNamespace(date_from=date(2026, 8, 1), date_to=date(2026, 8, 31)),
        currency="INR", freshness=SimpleNamespace(calculated_at=datetime.now(UTC)),
        completeness=SimpleNamespace(eligible_transaction_count=2, data_confidence="low")),
        metrics=SimpleNamespace(gross_income=metric, total_expense=metric, net_cash_flow=metric, savings_amount=metric))
    content = monthly_pdf(report)
    reader = PdfReader(io.BytesIO(content))
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    assert "Gross income: 123.4567" in text
    assert "Data confidence: low" in text
    assert "Currency: INR" in text


def test_month_and_erasure_contracts():
    assert month_dates("2024-02")[1] == date(2024, 2, 29)
    with pytest.raises(ApplicationError):
        month_dates("0000-01")
    with pytest.raises(ValidationError):
        ErasureRequest(password="secret", confirmation="yes")
    with pytest.raises(ValidationError):
        ErasureRequest(password="secret", confirmation="DELETE MY ACCOUNT", user_id=str(uuid4()))
    assert "secret" not in repr(ReauthenticationRequest(password="secret"))


@pytest.mark.parametrize("valid,exists", [(False, True), (True, False), (True, True)])
def test_reauthentication_checks_current_owner_password(valid, exists):
    owner = uuid4()
    session = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = SimpleNamespace(password_hash="encoded") if exists else None
    session.execute.return_value = result
    verify = MagicMock(return_value=valid)
    crypto = SimpleNamespace(passwords=SimpleNamespace(verify_password=verify))
    async def run():
        call = reauthenticate(session, SimpleNamespace(user_id=owner), ReauthenticationRequest(password=" untrimmed "), crypto)
        if valid and exists:
            await call
        else:
            with pytest.raises(ApplicationError) as failure:
                await call
            assert failure.value.status_code == 403
    asyncio.run(run())
    query = session.execute.call_args.args[0]
    assert owner in query.compile().params.values()
    assert "FOR UPDATE" in str(query)
    if exists:
        verify.assert_called_once_with(" untrimmed ", "encoded")


def test_export_is_owner_scoped_excludes_secrets_and_contains_decrypted_history():
    owner = uuid4()
    session = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = []
    session.execute.return_value = result
    history = SimpleNamespace(export_turns=AsyncMock(return_value=[{"question": "My goals", "answer": {"answer": "Evidence"}}]))
    content = asyncio.run(export_document(session, owner, history))
    document = json.loads(content)
    assert document["tables"]["assistant_conversation_turns"][0]["question"] == "My goals"
    assert "user_credentials" not in document["tables"]
    assert "refresh_tokens" not in document["tables"]
    assert "authentication_delivery_outbox" not in document["tables"]
    assert "notifications" in document["tables"]
    for call in session.execute.call_args_list:
        assert owner in call.args[0].compile().params.values()
        assert "WHERE" in str(call.args[0])


def test_export_refuses_truncation(monkeypatch):
    monkeypatch.setattr("falcon_api.workspace.MAX_EXPORT_ROWS", 0)
    session = AsyncMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = [{"id": uuid4()}]
    session.execute.return_value = result
    with pytest.raises(ApplicationError) as failure:
        asyncio.run(export_document(session, uuid4(), AsyncMock()))
    assert failure.value.status_code == 413


def test_json_export_does_not_round_decimal():
    assert json_value(Decimal("123456789012345.1234")) == "123456789012345.1234"
    assert json_value(date(2026, 8, 1)) == "2026-08-01"
    with pytest.raises(TypeError):
        json_value(b"secret")
