"""Secure, bounded extraction for digitally generated PDF statements."""

from __future__ import annotations

import io
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import pdfplumber
from falcon_api.core.errors import ApplicationError
from falcon_api.imports.extraction import (
    MAX_DATA_ROWS,
    MAX_UPLOAD_BYTES,
    ExtractedCell,
    ExtractedRow,
    ExtractedStatement,
)
from pdfminer.pdfparser import PDFSyntaxError
from pypdf import PdfReader
from pypdf.errors import PdfReadError, WrongPasswordError


MAX_PDF_PAGES = 100
PDF_MEDIA_TYPES = frozenset({"application/pdf"})
_WHITESPACE = re.compile(r"\s+")
_WORD_GROUP_GAP = 24.0
_LINE_TOLERANCE = 3.0


@dataclass(frozen=True, slots=True)
class PdfDocumentInfo:
    """Sanitized structural metadata passed to PDF adapters."""

    page_count: int
    encrypted: bool


class PdfStatementAdapter(Protocol):
    """Extract one supported digital statement layout into canonical rows."""

    name: str

    def can_handle(self, document: PdfDocumentInfo) -> bool:
        """Return whether the adapter can attempt this document safely."""

    def extract(
        self,
        content: bytes,
        *,
        password: str | None,
        header_row: int,
        max_rows: int,
    ) -> ExtractedStatement:
        """Return bounded inert cells or raise a bounded application error."""


class GenericDigitalPdfAdapter:
    """Read conventional text/table PDFs without OCR or provider guessing."""

    name = "generic_digital_pdf_v1"

    def can_handle(self, document: PdfDocumentInfo) -> bool:
        """Attempt every preflighted digital PDF within the page boundary."""
        return 0 < document.page_count <= MAX_PDF_PAGES

    def extract(
        self,
        content: bytes,
        *,
        password: str | None,
        header_row: int,
        max_rows: int,
    ) -> ExtractedStatement:
        """Extract tables first and fall back to aligned digital text lines."""
        table_rows: list[tuple[str | None, ...]] = []
        positioned_lines: list[list[tuple[str, float, float]]] = []
        try:
            with pdfplumber.open(io.BytesIO(content), password=password) as pdf:
                for page in pdf.pages:
                    deduplicated = page.dedupe_chars()
                    tables = deduplicated.extract_tables(
                        {
                            "vertical_strategy": "text",
                            "horizontal_strategy": "text",
                            "intersection_tolerance": 5,
                            "snap_tolerance": 3,
                            "join_tolerance": 3,
                        }
                    )
                    table_rows.extend(
                        tuple(cell for cell in row)
                        for table in tables
                        for row in table
                        if _row_has_value(row)
                    )
                    positioned_lines.extend(
                        _group_positioned_words(deduplicated.extract_words())
                    )
                    page.close()
        except (PDFSyntaxError, PdfReadError, OSError, TypeError, ValueError):
            raise _unsupported_pdf() from None

        positional_rows = _align_positioned_rows(
            positioned_lines,
            header_row=header_row,
        )
        for source_rows in (table_rows, positional_rows):
            try:
                statement = _collect_pdf_rows(
                    source_rows,
                    header_row=header_row,
                    max_rows=max_rows,
                    adapter_name=self.name,
                )
            except ApplicationError as exc:
                if exc.status_code == 413:
                    raise
                continue
            if _has_supported_mapping(statement):
                return statement
        raise _unsupported_pdf()


def extract_pdf_statement(
    content: bytes,
    *,
    password: str | None = None,
    header_row: int = 1,
    max_rows: int = MAX_DATA_ROWS,
    adapters: Sequence[PdfStatementAdapter] | None = None,
) -> ExtractedStatement:
    """Preflight one PDF and dispatch to the first compatible adapter."""
    document = _preflight_pdf(content, password=password)
    candidates = adapters or (GenericDigitalPdfAdapter(),)
    for adapter in candidates:
        if not adapter.can_handle(document):
            continue
        try:
            return adapter.extract(
                content,
                password=password,
                header_row=header_row,
                max_rows=max_rows,
            )
        except ApplicationError as exc:
            if exc.status_code == 413:
                raise
            continue
    raise ApplicationError(
        code="unsupported_statement_layout",
        message="The digital statement layout is not supported.",
        status_code=422,
    )


def _preflight_pdf(content: bytes, *, password: str | None) -> PdfDocumentInfo:
    if len(content) > MAX_UPLOAD_BYTES:
        raise ApplicationError(
            code="import_file_too_large",
            message="The import file exceeds the supported limit.",
            status_code=413,
        )
    if not content.startswith(b"%PDF-"):
        raise _unsupported_pdf()
    try:
        reader = PdfReader(io.BytesIO(content), strict=True)
        encrypted = reader.is_encrypted
        if encrypted:
            if not password or not reader.decrypt(password):
                raise _invalid_password()
        page_count = len(reader.pages)
        if page_count == 0 or page_count > MAX_PDF_PAGES:
            raise ApplicationError(
                code="import_file_too_large",
                message="The PDF statement exceeds the supported page limit.",
                status_code=413,
            )
        _reject_active_pdf_content(reader)
        return PdfDocumentInfo(page_count=page_count, encrypted=encrypted)
    except WrongPasswordError:
        raise _invalid_password() from None
    except ApplicationError:
        raise
    except (PdfReadError, OSError, TypeError, ValueError):
        raise _unsupported_pdf() from None


def _reject_active_pdf_content(reader: PdfReader) -> None:
    root = reader.trailer.get("/Root")
    if root is None:
        raise _unsupported_pdf()
    root_object = root.get_object()
    names = root_object.get("/Names")
    names_object = names.get_object() if names is not None else {}
    if (
        root_object.get("/OpenAction") is not None
        or root_object.get("/AA") is not None
        or names_object.get("/JavaScript") is not None
        or names_object.get("/EmbeddedFiles") is not None
    ):
        raise _unsupported_pdf()
    for page in reader.pages:
        if page.get("/AA") is not None:
            raise _unsupported_pdf()
        for annotation in page.get("/Annots", ()):
            annotation_object = annotation.get_object()
            action = annotation_object.get("/A")
            if action is not None and action.get_object().get("/S") == "/JavaScript":
                raise _unsupported_pdf()


def _collect_pdf_rows(
    source_rows: Sequence[Sequence[str | None]],
    *,
    header_row: int,
    max_rows: int,
    adapter_name: str,
) -> ExtractedStatement:
    if header_row < 1 or len(source_rows) < header_row:
        raise _unsupported_pdf()
    header_values = tuple(_clean_cell(value) for value in source_rows[header_row - 1])
    if not any(header_values):
        raise _unsupported_pdf()
    normalized_header = tuple(_normalize_cell(value) for value in header_values)
    header = ExtractedRow(
        row_number=header_row,
        cells=tuple(ExtractedCell(value) for value in header_values),
    )
    rows: list[ExtractedRow] = []
    for source_number, values in enumerate(source_rows[header_row:], start=header_row + 1):
        cleaned = tuple(_clean_cell(value) for value in values)
        if not any(cleaned) or tuple(_normalize_cell(value) for value in cleaned) == normalized_header:
            continue
        rows.append(
            ExtractedRow(
                row_number=source_number,
                cells=tuple(ExtractedCell(value) for value in cleaned),
            )
        )
        if len(rows) > max_rows:
            raise ApplicationError(
                code="import_file_too_large",
                message="The import file exceeds the supported row limit.",
                status_code=413,
            )
    if not rows:
        raise _unsupported_pdf()
    return ExtractedStatement(
        header=header,
        rows=tuple(rows),
        worksheet_name=None,
        adapter_name=adapter_name,
    )


def _row_has_value(row: Sequence[str | None]) -> bool:
    return any(value is not None and bool(str(value).strip()) for value in row)


def _clean_cell(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", str(value))).strip()
    return cleaned or None


def _normalize_cell(value: str | None) -> str:
    return "" if value is None else value.casefold()


def _group_positioned_words(
    words: Sequence[dict[str, object]],
) -> list[list[tuple[str, float, float]]]:
    ordered = sorted(
        (
            (str(word["text"]), float(word["x0"]), float(word["x1"]), float(word["top"]))
            for word in words
            if str(word.get("text", "")).strip()
        ),
        key=lambda value: (value[3], value[1]),
    )
    lines: list[list[tuple[str, float, float]]] = []
    line_tops: list[float] = []
    for text, x0, x1, top in ordered:
        if not lines or abs(top - line_tops[-1]) > _LINE_TOLERANCE:
            lines.append([])
            line_tops.append(top)
        lines[-1].append((text, x0, x1))
    return lines


def _align_positioned_rows(
    lines: Sequence[Sequence[tuple[str, float, float]]],
    *,
    header_row: int,
) -> list[tuple[str | None, ...]]:
    if header_row < 1 or len(lines) < header_row:
        return []
    header_groups = _merge_word_groups(lines[header_row - 1])
    if len(header_groups) < 2:
        return []
    starts = [group[1] for group in header_groups]
    boundaries = [
        (left + right) / 2
        for left, right in zip(starts, starts[1:])
    ]
    rows: list[tuple[str | None, ...]] = []
    for line in lines:
        cells: list[list[str]] = [[] for _ in header_groups]
        for text, x0, x1 in _merge_word_groups(line):
            center = (x0 + x1) / 2
            index = sum(center >= boundary for boundary in boundaries)
            cells[index].append(text)
        rows.append(
            tuple(" ".join(cell).strip() or None for cell in cells)
        )
    return rows


def _merge_word_groups(
    words: Sequence[tuple[str, float, float]],
) -> list[tuple[str, float, float]]:
    groups: list[tuple[str, float, float]] = []
    for text, x0, x1 in sorted(words, key=lambda value: value[1]):
        if groups and x0 - groups[-1][2] <= _WORD_GROUP_GAP:
            previous_text, previous_x0, _ = groups[-1]
            groups[-1] = (f"{previous_text} {text}", previous_x0, x1)
        else:
            groups.append((text, x0, x1))
    return groups


def _has_supported_mapping(statement: ExtractedStatement) -> bool:
    from falcon_api.imports.normalization import map_statement_columns

    try:
        map_statement_columns(statement.header)
    except ApplicationError:
        return False
    return True


def _invalid_password() -> ApplicationError:
    return ApplicationError(
        code="invalid_statement_password",
        message="The PDF statement password is missing or invalid.",
        status_code=422,
    )


def _unsupported_pdf() -> ApplicationError:
    return ApplicationError(
        code="unsupported_import_file",
        message="The PDF statement is malformed, active, scanned, or unsupported.",
        status_code=415,
    )
