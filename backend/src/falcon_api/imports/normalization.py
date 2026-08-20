"""Deterministic statement mapping, normalization, and duplicate hashes."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from falcon_api.core.errors import ApplicationError
from falcon_api.imports.extraction import (
    CellScalar,
    ExtractedCell,
    ExtractedRow,
    ExtractedStatement,
)
from falcon_api.models.enums import TransactionType
from falcon_api.schemas.imports import (
    ImportDateOrder,
    ImportIssueCode,
    ImportRowIssue,
)


MAX_PUBLIC_ISSUES = 100
MAX_INTEGRAL_AMOUNT = Decimal("1000000000000000")
_CURRENCY_SYMBOLS = {
    "₹": "INR",
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
}
_CURRENCY_CODE = re.compile(r"(?<![A-Za-z])([A-Za-z]{3})(?![A-Za-z])")
_NUMBER = re.compile(r"\d+(?:\.\d{1,4})?")
_WESTERN_GROUPING = re.compile(r"\d{1,3}(?:,\d{3})+")
_INDIAN_GROUPING = re.compile(r"\d{1,2}(?:,\d{2})*,\d{3}")
_WHITESPACE = re.compile(r"\s+")
_HEADER_PUNCTUATION = re.compile(r"[^\w]+", re.UNICODE)


class CanonicalColumn(StrEnum):
    """Reviewed statement meanings recognized by the first ETL release."""

    TRANSACTION_DATE = "transaction_date"
    DESCRIPTION = "description"
    AMOUNT = "amount"
    DEBIT = "debit"
    CREDIT = "credit"
    MERCHANT_NAME = "merchant_name"
    REFERENCE = "reference"


_HEADER_ALIASES = {
    CanonicalColumn.TRANSACTION_DATE: (
        "date",
        "transaction date",
        "txn date",
        "value date",
        "posting date",
    ),
    CanonicalColumn.DESCRIPTION: (
        "description",
        "narration",
        "particulars",
        "transaction details",
        "remarks",
    ),
    CanonicalColumn.AMOUNT: (
        "amount",
        "transaction amount",
        "txn amount",
    ),
    CanonicalColumn.DEBIT: (
        "debit",
        "debit amount",
        "withdrawal",
        "withdrawals",
    ),
    CanonicalColumn.CREDIT: (
        "credit",
        "credit amount",
        "deposit",
        "deposits",
    ),
    CanonicalColumn.MERCHANT_NAME: (
        "merchant",
        "merchant name",
        "payee",
        "counterparty",
    ),
    CanonicalColumn.REFERENCE: (
        "reference",
        "reference number",
        "transaction id",
        "txn id",
        "utr",
        "rrn",
    ),
}
_ALIAS_LOOKUP = {
    alias: column
    for column, aliases in _HEADER_ALIASES.items()
    for alias in aliases
}


@dataclass(frozen=True, slots=True)
class ColumnMapping:
    """Map canonical meanings to zero-based source column positions."""

    positions: dict[CanonicalColumn, int]

    def index(self, column: CanonicalColumn) -> int | None:
        """Return the source position for an optional canonical column."""
        return self.positions.get(column)


@dataclass(frozen=True, slots=True)
class NormalizedImportRow:
    """One validated ledger-ready row with private duplicate identity."""

    row_number: int
    transaction_type: TransactionType
    signed_amount: Decimal
    transaction_date: date
    description: str
    merchant_name: str | None
    source_reference: str | None
    external_source_hash: str


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    """Reconcile accepted rows and bounded public row issues."""

    rows: tuple[NormalizedImportRow, ...]
    issues: tuple[ImportRowIssue, ...]
    accepted_count: int
    rejected_count: int
    issues_truncated: bool


@dataclass(frozen=True, slots=True)
class _RowProblem(Exception):
    code: ImportIssueCode
    message: str


def file_fingerprint(content: bytes) -> str:
    """Return the lowercase SHA-256 identity of the exact uploaded bytes."""
    return hashlib.sha256(content).hexdigest()


def map_statement_columns(header: ExtractedRow) -> ColumnMapping:
    """Resolve reviewed aliases and reject ambiguous required mappings."""
    positions: dict[CanonicalColumn, int] = {}
    for index, cell in enumerate(header.cells):
        if cell.formula_without_value:
            continue
        normalized = normalize_header(cell.value)
        column = _ALIAS_LOOKUP.get(normalized)
        if column is None:
            continue
        if column in positions:
            raise _invalid_mapping()
        positions[column] = index

    required = {
        CanonicalColumn.TRANSACTION_DATE,
        CanonicalColumn.DESCRIPTION,
    }
    if not required.issubset(positions):
        raise _invalid_mapping()

    has_amount = CanonicalColumn.AMOUNT in positions
    has_debit = CanonicalColumn.DEBIT in positions
    has_credit = CanonicalColumn.CREDIT in positions
    if has_amount == (has_debit or has_credit):
        raise _invalid_mapping()
    if not has_amount and not (has_debit and has_credit):
        raise _invalid_mapping()
    return ColumnMapping(positions=positions)


def normalize_header(value: CellScalar) -> str:
    """Normalize a header without interpreting its financial meaning."""
    if value is None or isinstance(value, (date, datetime, bool)):
        return ""
    text = unicodedata.normalize("NFKC", str(value)).casefold()
    text = _HEADER_PUNCTUATION.sub(" ", text.replace("_", " "))
    return _WHITESPACE.sub(" ", text).strip()


def normalize_statement(
    statement: ExtractedStatement,
    *,
    date_order: ImportDateOrder,
    account_currency: str,
    today: date,
    existing_hashes: frozenset[str] = frozenset(),
    max_issues: int = MAX_PUBLIC_ISSUES,
) -> NormalizationResult:
    """Map, validate, hash, and reconcile every non-blank source row."""
    currency = account_currency.strip().upper()
    if re.fullmatch(r"[A-Z]{3}", currency) is None:
        raise ValueError("account_currency must be an ISO-style code.")
    if max_issues < 0:
        raise ValueError("max_issues must be non-negative.")

    mapping = map_statement_columns(statement.header)
    accepted: list[NormalizedImportRow] = []
    issues: list[ImportRowIssue] = []
    rejected_count = 0
    issues_truncated = False
    occurrences: Counter[str] = Counter()
    seen_hashes: set[str] = set()

    for row in statement.rows:
        if _is_blank_row(row):
            continue
        try:
            normalized = _normalize_row(
                row,
                mapping=mapping,
                date_order=date_order,
                account_currency=currency,
                today=today,
                occurrences=occurrences,
            )
            if (
                normalized.external_source_hash in existing_hashes
                or normalized.external_source_hash in seen_hashes
            ):
                raise _RowProblem(
                    ImportIssueCode.DUPLICATE_TRANSACTION,
                    "The transaction duplicates an existing imported entry.",
                )
            seen_hashes.add(normalized.external_source_hash)
            accepted.append(normalized)
        except _RowProblem as problem:
            rejected_count += 1
            if len(issues) < max_issues:
                issues.append(
                    ImportRowIssue(
                        row_number=row.row_number,
                        code=problem.code,
                        message=problem.message,
                    )
                )
            else:
                issues_truncated = True

    return NormalizationResult(
        rows=tuple(accepted),
        issues=tuple(issues),
        accepted_count=len(accepted),
        rejected_count=rejected_count,
        issues_truncated=issues_truncated,
    )


def _normalize_row(
    row: ExtractedRow,
    *,
    mapping: ColumnMapping,
    date_order: ImportDateOrder,
    account_currency: str,
    today: date,
    occurrences: Counter[str],
) -> NormalizedImportRow:
    transaction_date = _parse_date(
        _mapped_cell(row, mapping, CanonicalColumn.TRANSACTION_DATE),
        date_order=date_order,
    )
    if transaction_date > today:
        raise _RowProblem(
            ImportIssueCode.FUTURE_DATE,
            "The transaction date cannot be in the future.",
        )
    signed_amount = _parse_mapped_amount(
        row,
        mapping=mapping,
        account_currency=account_currency,
    )
    description = _normalize_required_text(
        _mapped_cell(row, mapping, CanonicalColumn.DESCRIPTION),
        max_length=500,
    )
    merchant = _normalize_optional_text(
        _mapped_cell(row, mapping, CanonicalColumn.MERCHANT_NAME),
        max_length=200,
    )
    reference = _normalize_optional_text(
        _mapped_cell(row, mapping, CanonicalColumn.REFERENCE),
        max_length=255,
    )
    transaction_type = (
        TransactionType.INCOME
        if signed_amount > 0
        else TransactionType.EXPENSE
    )
    hash_value = _transaction_hash(
        transaction_date=transaction_date,
        signed_amount=signed_amount,
        description=description,
        merchant=merchant,
        reference=reference,
        occurrences=occurrences,
    )
    return NormalizedImportRow(
        row_number=row.row_number,
        transaction_type=transaction_type,
        signed_amount=signed_amount,
        transaction_date=transaction_date,
        description=description,
        merchant_name=merchant,
        source_reference=reference,
        external_source_hash=hash_value,
    )


def _parse_mapped_amount(
    row: ExtractedRow,
    *,
    mapping: ColumnMapping,
    account_currency: str,
) -> Decimal:
    amount_index = mapping.index(CanonicalColumn.AMOUNT)
    if amount_index is not None:
        return _parse_amount(
            _cell_at(row, amount_index),
            account_currency=account_currency,
            allow_negative=True,
        )

    debit = _parse_optional_magnitude(
        _mapped_cell(row, mapping, CanonicalColumn.DEBIT),
        account_currency=account_currency,
    )
    credit = _parse_optional_magnitude(
        _mapped_cell(row, mapping, CanonicalColumn.CREDIT),
        account_currency=account_currency,
    )
    debit_nonzero = debit is not None and debit != 0
    credit_nonzero = credit is not None and credit != 0
    if debit_nonzero and credit_nonzero:
        raise _RowProblem(
            ImportIssueCode.AMBIGUOUS_AMOUNT,
            "Exactly one debit or credit amount is required.",
        )
    if debit_nonzero:
        return -debit
    if credit_nonzero:
        return credit
    if debit is not None or credit is not None:
        raise _RowProblem(
            ImportIssueCode.ZERO_AMOUNT,
            "The transaction amount must be non-zero.",
        )
    raise _RowProblem(
        ImportIssueCode.MISSING_AMOUNT,
        "The transaction amount is required.",
    )


def _parse_optional_magnitude(
    cell: ExtractedCell,
    *,
    account_currency: str,
) -> Decimal | None:
    _reject_uncached_formula(cell)
    if _cell_is_blank(cell):
        return None
    value = _parse_amount(
        cell,
        account_currency=account_currency,
        allow_negative=False,
        allow_zero=True,
    )
    return value


def _parse_amount(
    cell: ExtractedCell,
    *,
    account_currency: str,
    allow_negative: bool,
    allow_zero: bool = False,
) -> Decimal:
    _reject_uncached_formula(cell)
    value = cell.value
    if value is None or isinstance(value, (date, datetime, time, bool)):
        raise _RowProblem(
            ImportIssueCode.MISSING_AMOUNT
            if value is None
            else ImportIssueCode.INVALID_AMOUNT,
            "The transaction amount is invalid.",
        )
    text = unicodedata.normalize("NFKC", str(value)).strip()
    if not text:
        raise _RowProblem(
            ImportIssueCode.MISSING_AMOUNT,
            "The transaction amount is required.",
        )

    negative_parentheses = text.startswith("(") and text.endswith(")")
    if negative_parentheses:
        text = text[1:-1].strip()
    symbols = {symbol for symbol in _CURRENCY_SYMBOLS if symbol in text}
    if any(_CURRENCY_SYMBOLS[symbol] != account_currency for symbol in symbols):
        raise _RowProblem(
            ImportIssueCode.INVALID_CURRENCY,
            "The transaction currency does not match the account.",
        )
    for symbol in symbols:
        text = text.replace(symbol, "")

    codes = {match.upper() for match in _CURRENCY_CODE.findall(text)}
    if any(code != account_currency for code in codes):
        raise _RowProblem(
            ImportIssueCode.INVALID_CURRENCY,
            "The transaction currency does not match the account.",
        )
    text = _CURRENCY_CODE.sub("", text)
    text = "".join(text.split())

    explicit_negative = text.startswith("-")
    explicit_positive = text.startswith("+")
    if explicit_negative or explicit_positive:
        text = text[1:]
    if negative_parentheses and (explicit_negative or explicit_positive):
        raise _invalid_amount_problem()
    if "," in text:
        integral, dot, fraction = text.partition(".")
        if not (
            _WESTERN_GROUPING.fullmatch(integral)
            or _INDIAN_GROUPING.fullmatch(integral)
        ):
            raise _invalid_amount_problem()
        text = integral.replace(",", "") + (dot + fraction if dot else "")
    if _NUMBER.fullmatch(text) is None:
        raise _invalid_amount_problem()
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise _invalid_amount_problem() from None
    if negative_parentheses or explicit_negative:
        amount = -amount
    if amount == 0:
        if allow_zero:
            return amount
        raise _RowProblem(
            ImportIssueCode.ZERO_AMOUNT,
            "The transaction amount must be non-zero.",
        )
    if amount.copy_abs() >= MAX_INTEGRAL_AMOUNT or amount.as_tuple().exponent < -4:
        raise _invalid_amount_problem()
    if not allow_negative and amount < 0:
        raise _invalid_amount_problem()
    return amount


def _parse_date(cell: ExtractedCell, *, date_order: ImportDateOrder) -> date:
    _reject_uncached_formula(cell)
    value = cell.value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None or isinstance(value, (int, float, bool, time)):
        raise _RowProblem(
            ImportIssueCode.MISSING_DATE
            if value is None
            else ImportIssueCode.INVALID_DATE,
            "The transaction date is invalid.",
        )
    text = _normalize_text(value)
    if not text:
        raise _RowProblem(
            ImportIssueCode.MISSING_DATE,
            "The transaction date is required.",
        )

    numeric_formats = {
        ImportDateOrder.DAY_FIRST: ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"),
        ImportDateOrder.MONTH_FIRST: ("%m/%d/%Y", "%m-%d-%Y", "%m.%d.%Y"),
        ImportDateOrder.YEAR_FIRST: ("%Y/%m/%d", "%Y-%m-%d", "%Y.%m.%d"),
    }
    formats = ("%Y-%m-%d", "%d %b %Y", "%d %B %Y") + numeric_formats[date_order]
    for date_format in formats:
        try:
            return datetime.strptime(text, date_format).date()
        except ValueError:
            continue
    raise _RowProblem(
        ImportIssueCode.INVALID_DATE,
        "The transaction date is invalid.",
    )


def _normalize_required_text(cell: ExtractedCell, *, max_length: int) -> str:
    _reject_uncached_formula(cell)
    if cell.value is None:
        raise _RowProblem(
            ImportIssueCode.MISSING_DESCRIPTION,
            "The transaction description is required.",
        )
    value = _normalize_text(cell.value)
    if not value:
        raise _RowProblem(
            ImportIssueCode.MISSING_DESCRIPTION,
            "The transaction description is required.",
        )
    _validate_safe_text(value)
    if len(value) > max_length:
        raise _RowProblem(
            ImportIssueCode.DESCRIPTION_TOO_LONG,
            "The transaction description is too long.",
        )
    return value


def _normalize_optional_text(
    cell: ExtractedCell,
    *,
    max_length: int,
) -> str | None:
    if _cell_is_blank(cell):
        return None
    _reject_uncached_formula(cell)
    value = _normalize_text(cell.value)
    _validate_safe_text(value)
    if len(value) > max_length:
        raise _RowProblem(
            ImportIssueCode.INVALID_DESCRIPTION,
            "Optional transaction text is invalid.",
        )
    return value or None


def _validate_safe_text(value: str) -> None:
    if any(
        unicodedata.category(character).startswith("C")
        for character in value
    ):
        raise _RowProblem(
            ImportIssueCode.INVALID_DESCRIPTION,
            "Transaction text contains unsupported characters.",
        )


def _transaction_hash(
    *,
    transaction_date: date,
    signed_amount: Decimal,
    description: str,
    merchant: str | None,
    reference: str | None,
    occurrences: Counter[str],
) -> str:
    if reference:
        identity = json.dumps(
            ["v1", "reference", reference.casefold()],
            ensure_ascii=False,
            separators=(",", ":"),
        )
    else:
        normalized_amount = format(signed_amount.normalize(), "f")
        base = json.dumps(
            [
                "v1",
                "fields",
                transaction_date.isoformat(),
                normalized_amount,
                description.casefold(),
                (merchant or "").casefold(),
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        occurrences[base] += 1
        identity = json.dumps(
            [base, occurrences[base]],
            ensure_ascii=False,
            separators=(",", ":"),
        )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _mapped_cell(
    row: ExtractedRow,
    mapping: ColumnMapping,
    column: CanonicalColumn,
) -> ExtractedCell:
    index = mapping.index(column)
    return ExtractedCell(None) if index is None else _cell_at(row, index)


def _cell_at(row: ExtractedRow, index: int) -> ExtractedCell:
    return row.cells[index] if index < len(row.cells) else ExtractedCell(None)


def _is_blank_row(row: ExtractedRow) -> bool:
    return all(_cell_is_blank(cell) for cell in row.cells)


def _cell_is_blank(cell: ExtractedCell) -> bool:
    return cell.value is None or (
        isinstance(cell.value, str) and not cell.value.strip()
    )


def _normalize_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value))
    return _WHITESPACE.sub(" ", text).strip()


def _reject_uncached_formula(cell: ExtractedCell) -> None:
    if cell.formula_without_value:
        raise _RowProblem(
            ImportIssueCode.UNCACHED_FORMULA,
            "A required formula cell has no cached value.",
        )


def _invalid_amount_problem() -> _RowProblem:
    return _RowProblem(
        ImportIssueCode.INVALID_AMOUNT,
        "The transaction amount is invalid.",
    )


def _invalid_mapping() -> ApplicationError:
    return ApplicationError(
        code="invalid_import_mapping",
        message="The statement columns could not be mapped safely.",
        status_code=422,
    )
