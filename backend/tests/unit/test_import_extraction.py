"""Security and behavior tests for statement source extraction."""

import asyncio
import io
import warnings
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from falcon_api.core.errors import ApplicationError
from falcon_api.imports.extraction import (
    CSV_MEDIA_TYPES,
    XLSX_MEDIA_TYPES,
    extract_csv,
    extract_statement,
    extract_xlsx,
    read_bounded_upload,
)
from falcon_api.schemas.imports import StatementImportOptions
from openpyxl import Workbook


class _Upload:
    def __init__(self, content: bytes) -> None:
        self._content = content
        self._position = 0
        self.read_sizes: list[int] = []

    async def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        start = self._position
        end = len(self._content) if size < 0 else start + size
        self._position = min(end, len(self._content))
        return self._content[start : self._position]


def _workbook_bytes(
    rows: list[list[object]],
    *,
    sheet_name: str = "Transactions",
) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    for row in rows:
        sheet.append(row)
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _add_archive_member(content: bytes, name: str, value: bytes) -> bytes:
    source = ZipFile(io.BytesIO(content))
    output = io.BytesIO()
    with source, ZipFile(output, "w", compression=ZIP_DEFLATED) as target:
        for entry in source.infolist():
            target.writestr(entry, source.read(entry.filename))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            target.writestr(name, value)
    return output.getvalue()


def _assert_error(info: pytest.ExceptionInfo[ApplicationError], code: str) -> None:
    assert info.value.code == code


def test_bounded_upload_reads_in_chunks() -> None:
    upload = _Upload(b"date,amount\n2026-08-20,10\n")

    content = asyncio.run(read_bounded_upload(upload, max_bytes=100))

    assert content.startswith(b"date,amount")
    assert upload.read_sizes
    assert all(size <= 101 for size in upload.read_sizes)


def test_bounded_upload_stops_after_first_excess_byte() -> None:
    upload = _Upload(b"123456")

    with pytest.raises(ApplicationError) as info:
        asyncio.run(read_bounded_upload(upload, max_bytes=5))

    _assert_error(info, "import_file_too_large")


@pytest.mark.parametrize("delimiter", [",", ";", "\t"])
def test_csv_extracts_reviewed_delimiters_and_source_rows(delimiter: str) -> None:
    content = (
        "ignored\n"
        f"Date{delimiter}Description{delimiter}Amount\n"
        f"20/08/2026{delimiter}Groceries{delimiter}-1250.50\n"
    ).encode()

    statement = extract_csv(content, header_row=2)

    assert statement.header.row_number == 2
    assert tuple(cell.value for cell in statement.header.cells) == (
        "Date",
        "Description",
        "Amount",
    )
    assert statement.rows[0].row_number == 3
    assert statement.rows[0].cells[1].value == "Groceries"


def test_csv_accepts_utf8_bom() -> None:
    statement = extract_csv(
        b"\xef\xbb\xbfDate,Description,Amount\n2026-08-20,Cafe,-200\n"
    )

    assert statement.header.cells[0].value == "Date"


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"\xff\xfeD\x00a\x00t\x00e\x00",
        b"Date,Description\x00,Amount\n2026-08-20,Cafe,-200\n",
        b"Date|Description|Amount\n2026-08-20|Cafe|-200\n",
    ],
)
def test_csv_rejects_empty_or_unsupported_content(content: bytes) -> None:
    with pytest.raises(ApplicationError) as info:
        extract_csv(content)

    assert info.value.code in {
        "invalid_import_mapping",
        "unsupported_import_file",
    }


def test_csv_enforces_physical_row_limit() -> None:
    content = b"Date,Amount\n2026-08-19,1\n2026-08-20,2\n"

    with pytest.raises(ApplicationError) as info:
        extract_csv(content, max_rows=1)

    _assert_error(info, "import_file_too_large")


def test_dispatcher_requires_matching_csv_metadata() -> None:
    options = StatementImportOptions(
        account_id="216f5b26-c821-4a03-a3be-1d6077aed034",
        source_type="csv",
    )
    content = b"Date,Amount\n2026-08-20,1\n"

    statement = extract_statement(
        content,
        filename="statement.CSV",
        content_type=next(iter(CSV_MEDIA_TYPES)) + "; charset=utf-8",
        options=options,
    )
    assert len(statement.rows) == 1

    with pytest.raises(ApplicationError) as info:
        extract_statement(
            content,
            filename="statement.xlsx",
            content_type="text/csv",
            options=options,
        )
    _assert_error(info, "unsupported_import_file")


def test_xlsx_extracts_selected_sheet_and_typed_values() -> None:
    content = _workbook_bytes(
        [
            ["Date", "Description", "Amount"],
            ["2026-08-20", "Groceries", -1250.5],
        ]
    )

    statement = extract_xlsx(content, sheet_name="Transactions")

    assert statement.worksheet_name == "Transactions"
    assert statement.rows[0].cells[1].value == "Groceries"
    assert statement.rows[0].cells[2].value == -1250.5


def test_xlsx_never_returns_formula_text() -> None:
    content = _workbook_bytes(
        [
            ["Date", "Description", "Amount"],
            ["2026-08-20", "Calculated", "=1+1"],
        ]
    )

    cell = extract_xlsx(content).rows[0].cells[2]

    assert cell.value is None
    assert cell.formula_without_value is True


def test_xlsx_rejects_missing_sheet_and_excess_rows() -> None:
    content = _workbook_bytes(
        [["Date", "Amount"], ["2026-08-19", 1], ["2026-08-20", 2]]
    )

    with pytest.raises(ApplicationError) as missing:
        extract_xlsx(content, sheet_name="Missing")
    _assert_error(missing, "invalid_import_mapping")

    with pytest.raises(ApplicationError) as large:
        extract_xlsx(content, max_rows=1)
    _assert_error(large, "import_file_too_large")


@pytest.mark.parametrize(
    "member_name",
    ["../escape.xml", "xl/vbaProject.bin", "xl/externalLinks/link.xml"],
)
def test_xlsx_rejects_traversal_macros_and_external_links(
    member_name: str,
) -> None:
    content = _add_archive_member(
        _workbook_bytes([["Date", "Amount"]]),
        member_name,
        b"unsafe",
    )

    with pytest.raises(ApplicationError) as info:
        extract_xlsx(content)

    _assert_error(info, "unsupported_import_file")


def test_xlsx_rejects_explosive_compression_ratio() -> None:
    content = _add_archive_member(
        _workbook_bytes([["Date", "Amount"]]),
        "docProps/padding.bin",
        b"0" * 200_000,
    )

    with pytest.raises(ApplicationError) as info:
        extract_xlsx(content)

    _assert_error(info, "unsupported_import_file")


def test_xlsx_rejects_duplicate_or_missing_required_archive_parts() -> None:
    workbook = _workbook_bytes([["Date", "Amount"]])
    duplicate = _add_archive_member(
        workbook,
        "xl/workbook.xml",
        b"<workbook />",
    )

    with pytest.raises(ApplicationError) as duplicate_info:
        extract_xlsx(duplicate)
    _assert_error(duplicate_info, "unsupported_import_file")

    unrelated = io.BytesIO()
    with ZipFile(unrelated, "w") as archive:
        archive.writestr("document.txt", "not a workbook")

    with pytest.raises(ApplicationError) as missing_info:
        extract_xlsx(unrelated.getvalue())
    _assert_error(missing_info, "unsupported_import_file")


def test_dispatcher_requires_matching_xlsx_metadata() -> None:
    options = StatementImportOptions(
        account_id="216f5b26-c821-4a03-a3be-1d6077aed034",
        source_type="excel",
    )
    content = _workbook_bytes([["Date", "Amount"], ["2026-08-20", 1]])

    statement = extract_statement(
        content,
        filename="statement.xlsx",
        content_type=next(iter(XLSX_MEDIA_TYPES)),
        options=options,
    )
    assert len(statement.rows) == 1

    with pytest.raises(ApplicationError) as info:
        extract_statement(
            content,
            filename="statement.xlsx",
            content_type="application/octet-stream",
            options=options,
        )
    _assert_error(info, "unsupported_import_file")
