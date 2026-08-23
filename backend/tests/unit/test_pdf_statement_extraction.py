"""Security, adapter, and password tests for digital PDF statements."""

import io
from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import pytest
from falcon_api.core.errors import ApplicationError
from falcon_api.imports.extraction import ExtractedCell, ExtractedRow, ExtractedStatement
from falcon_api.imports.pdf_extraction import (
    GenericDigitalPdfAdapter,
    PdfDocumentInfo,
    _collect_pdf_rows,
    extract_pdf_statement,
)
from falcon_api.imports.normalization import normalize_statement
from falcon_api.models.enums import ImportDateOrder
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


class _Adapter:
    name = "test_adapter_v1"

    def __init__(self, statement: ExtractedStatement) -> None:
        self.statement = statement
        self.document: PdfDocumentInfo | None = None
        self.password: str | None = None

    def can_handle(self, document: PdfDocumentInfo) -> bool:
        self.document = document
        return True

    def extract(
        self,
        content: bytes,
        *,
        password: str | None,
        header_row: int,
        max_rows: int,
    ) -> ExtractedStatement:
        self.password = password
        return self.statement


def _pdf(*, pages: int = 1, password: str | None = None, active: bool = False) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    if password:
        writer.encrypt(password)
    if active:
        writer.add_js("app.alert('unsafe')")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def _statement() -> ExtractedStatement:
    return ExtractedStatement(
        header=ExtractedRow(
            row_number=1,
            cells=(ExtractedCell("Date"), ExtractedCell("Amount")),
        ),
        rows=(
            ExtractedRow(
                row_number=2,
                cells=(ExtractedCell("2026-08-20"), ExtractedCell("10")),
            ),
        ),
        adapter_name="test_adapter_v1",
    )


def _digital_statement_pdf() -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_reference = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): font_reference}
            )
        }
    )
    values = (
        ("Date", 50, 740),
        ("Description", 160, 740),
        ("Debit", 350, 740),
        ("Credit", 430, 740),
        ("Balance", 510, 740),
        ("19/08/2026", 50, 710),
        ("Groceries", 160, 710),
        ("100", 350, 710),
        ("900", 510, 710),
        ("20/08/2026", 50, 680),
        ("Salary", 160, 680),
        ("500", 430, 680),
        ("1400", 510, 680),
    )
    stream = "\n".join(
        f"BT /F1 10 Tf {x} {y} Td ({text}) Tj ET"
        for text, x, y in values
    ).encode()
    content = DecodedStreamObject()
    content.set_data(stream)
    page[NameObject("/Contents")] = writer._add_object(content)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def _assert_error(info: pytest.ExceptionInfo[ApplicationError], code: str) -> None:
    assert info.value.code == code


def test_preflight_dispatches_bounded_pdf_to_adapter() -> None:
    adapter = _Adapter(_statement())

    result = extract_pdf_statement(_pdf(), adapters=(adapter,))

    assert result.adapter_name == "test_adapter_v1"
    assert adapter.document == PdfDocumentInfo(page_count=1, encrypted=False)


def test_real_digital_pdf_extracts_normalizes_and_reconciles() -> None:
    statement = extract_pdf_statement(_digital_statement_pdf())
    result = normalize_statement(
        statement,
        date_order=ImportDateOrder.DAY_FIRST,
        account_currency="INR",
        today=date(2026, 8, 20),
    )

    assert statement.adapter_name == "generic_digital_pdf_v1"
    assert [row.signed_amount for row in result.rows] == [
        Decimal("-100"),
        Decimal("500"),
    ]
    assert result.balance_reconciled is True


def test_encrypted_pdf_requires_and_forwards_ephemeral_password() -> None:
    content = _pdf(password="secret")

    with pytest.raises(ApplicationError) as missing:
        extract_pdf_statement(content, adapters=(_Adapter(_statement()),))
    _assert_error(missing, "invalid_statement_password")

    adapter = _Adapter(_statement())
    result = extract_pdf_statement(content, password="secret", adapters=(adapter,))

    assert result.rows
    assert adapter.password == "secret"
    assert adapter.document == PdfDocumentInfo(page_count=1, encrypted=True)


@pytest.mark.parametrize("content", [b"", b"not-a-pdf", b"%PDF-broken"])
def test_pdf_rejects_malformed_content(content: bytes) -> None:
    with pytest.raises(ApplicationError) as info:
        extract_pdf_statement(content)

    _assert_error(info, "unsupported_import_file")


def test_pdf_rejects_active_content_and_page_overflow() -> None:
    with pytest.raises(ApplicationError) as active:
        extract_pdf_statement(_pdf(active=True))
    _assert_error(active, "unsupported_import_file")

    with pytest.raises(ApplicationError) as pages:
        extract_pdf_statement(_pdf(pages=101))
    _assert_error(pages, "import_file_too_large")


def test_pdf_row_collection_removes_repeated_headers_and_enforces_limit() -> None:
    rows = [
        ("Date", "Description", "Debit", "Credit", "Balance"),
        ("20/08/2026", "Groceries", "100", None, "900"),
        ("Date", "Description", "Debit", "Credit", "Balance"),
        ("21/08/2026", "Salary", None, "500", "1400"),
    ]

    statement = _collect_pdf_rows(
        rows,
        header_row=1,
        max_rows=2,
        adapter_name="generic_digital_pdf_v1",
    )

    assert len(statement.rows) == 2
    assert statement.rows[1].cells[1].value == "Salary"
    assert statement.adapter_name == "generic_digital_pdf_v1"

    with pytest.raises(ApplicationError) as large:
        _collect_pdf_rows(
            rows,
            header_row=1,
            max_rows=1,
            adapter_name="generic_digital_pdf_v1",
        )
    _assert_error(large, "import_file_too_large")


def test_generic_adapter_prefers_tables_and_closes_page(monkeypatch) -> None:
    page = Mock()
    page.dedupe_chars.return_value = page
    page.extract_tables.return_value = [
        [
            ["Date", "Description", "Amount"],
            ["20/08/2026", "Groceries", "-100"],
        ]
    ]
    page.extract_words.return_value = []
    pdf = Mock()
    pdf.pages = [page]
    context = Mock()
    context.__enter__ = Mock(return_value=pdf)
    context.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(
        "falcon_api.imports.pdf_extraction.pdfplumber.open",
        Mock(return_value=context),
    )

    statement = GenericDigitalPdfAdapter().extract(
        b"%PDF-fixture",
        password=None,
        header_row=1,
        max_rows=10,
    )

    assert statement.rows[0].cells[1].value == "Groceries"
    page.close.assert_called_once_with()
