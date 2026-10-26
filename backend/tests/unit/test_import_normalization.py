"""Tests for deterministic statement normalization and duplicate identity."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from falcon_api.core.errors import ApplicationError
from falcon_api.imports.extraction import (
    ExtractedCell,
    ExtractedRow,
    ExtractedStatement,
)
from falcon_api.imports.normalization import (
    CanonicalColumn,
    file_fingerprint,
    map_statement_columns,
    normalize_header,
    normalize_statement,
)
from falcon_api.models.enums import TransactionType
from falcon_api.schemas.imports import ImportDateOrder, ImportIssueCode


def _row(number: int, *values: object) -> ExtractedRow:
    return ExtractedRow(
        row_number=number,
        cells=tuple(ExtractedCell(value) for value in values),  # type: ignore[arg-type]
    )


def _statement(
    headers: tuple[object, ...],
    *rows: tuple[object, ...],
) -> ExtractedStatement:
    return ExtractedStatement(
        header=_row(1, *headers),
        rows=tuple(_row(index, *values) for index, values in enumerate(rows, 2)),
    )


def _normalize(
    statement: ExtractedStatement,
    **overrides: object,
):
    arguments = {
        "date_order": ImportDateOrder.DAY_FIRST,
        "account_currency": "INR",
        "today": date(2026, 8, 20),
    }
    arguments.update(overrides)
    return normalize_statement(statement, **arguments)  # type: ignore[arg-type]


def test_header_normalization_handles_unicode_case_and_punctuation() -> None:
    assert normalize_header("  Transaction_Date  ") == "transaction date"
    assert normalize_header("ＴＸＮ—DATE") == "txn date"
    assert normalize_header(None) == ""
    assert normalize_header(True) == ""


def test_mapping_accepts_reviewed_aliases_and_ignores_unknown_columns() -> None:
    mapping = map_statement_columns(
        _row(1, "Value Date", "Narration", "Withdrawal", "Deposit", "Notes")
    )

    assert mapping.index(CanonicalColumn.TRANSACTION_DATE) == 0
    assert mapping.index(CanonicalColumn.DESCRIPTION) == 1
    assert mapping.index(CanonicalColumn.DEBIT) == 2
    assert mapping.index(CanonicalColumn.CREDIT) == 3
    assert mapping.index(CanonicalColumn.REFERENCE) is None


@pytest.mark.parametrize(
    "headers",
    [
        ("Description", "Amount"),
        ("Date", "Amount"),
        ("Date", "Description"),
        ("Date", "Description", "Amount", "Debit", "Credit"),
        ("Date", "Description", "Debit"),
        ("Date", "Description", "Amount", "Transaction Amount"),
    ],
)
def test_mapping_rejects_missing_or_ambiguous_columns(
    headers: tuple[str, ...],
) -> None:
    with pytest.raises(ApplicationError) as info:
        map_statement_columns(_row(1, *headers))

    assert info.value.code == "invalid_import_mapping"


def test_signed_amount_rows_become_ledger_ready_income_and_expense() -> None:
    statement = _statement(
        ("Date", "Description", "Amount", "Merchant", "Reference"),
        ("20/08/2026", "  Salary  ", "₹ 50,000.00", "Employer", "SAL-1"),
        ("19/08/2026", "Cafe", "(₹1,250.50)", "  Local Café  ", "CAFE-1"),
    )

    result = _normalize(statement)

    assert result.accepted_count == 2
    assert result.rejected_count == 0
    assert result.rows[0].transaction_type is TransactionType.INCOME
    assert result.rows[0].signed_amount == Decimal("50000.00")
    assert result.rows[1].transaction_type is TransactionType.EXPENSE
    assert result.rows[1].signed_amount == Decimal("-1250.50")
    assert result.rows[1].merchant_name == "Local Café"
    assert len(result.rows[0].external_source_hash) == 64


def test_debit_credit_rows_map_to_signed_amounts() -> None:
    statement = _statement(
        ("Txn Date", "Particulars", "Debit Amount", "Credit Amount"),
        (date(2026, 8, 19), "Groceries", "1,250", ""),
        (datetime(2026, 8, 20, 10, 30), "Refund", "0", "500"),
    )

    result = _normalize(statement)

    assert [row.signed_amount for row in result.rows] == [
        Decimal("-1250"),
        Decimal("500"),
    ]


def test_running_balances_reconcile_in_ascending_or_descending_order() -> None:
    ascending = _normalize(
        _statement(
            ("Date", "Description", "Amount", "Running Balance"),
            ("18/08/2026", "Opening credit", "100", "1000"),
            ("19/08/2026", "Groceries", "-100", "900"),
            ("20/08/2026", "Salary", "500", "1400"),
        )
    )
    descending = _normalize(
        _statement(
            ("Date", "Description", "Amount", "Balance"),
            ("20/08/2026", "Salary", "500", "1400"),
            ("19/08/2026", "Groceries", "-100", "900"),
            ("18/08/2026", "Opening credit", "100", "1000"),
        )
    )

    assert ascending.balance_reconciled is True
    assert descending.balance_reconciled is True
    assert ascending.rows[0].source_balance == Decimal("1000")


def test_running_balance_mismatch_is_detected_without_rejecting_rows() -> None:
    result = _normalize(
        _statement(
            ("Date", "Description", "Amount", "Available Balance"),
            ("19/08/2026", "Groceries", "-100", "900"),
            ("20/08/2026", "Salary", "500", "999"),
        )
    )

    assert result.accepted_count == 2
    assert result.balance_reconciled is False


def test_balance_reconciliation_is_unknown_when_balance_is_absent() -> None:
    result = _normalize(
        _statement(
            ("Date", "Description", "Amount"),
            ("20/08/2026", "Salary", "500"),
        )
    )

    assert result.balance_reconciled is None


@pytest.mark.parametrize(
    "rows",
    [
        (
            ("19/08/2026", "Groceries", "-100", "900"),
            ("20/08/2026", "Salary", "500", ""),
        ),
        (
            ("19/08/2026", "Groceries", "-100", "900"),
            ("not-a-date", "Salary", "500", "1400"),
        ),
    ],
)
def test_balance_reconciliation_is_unknown_when_sequence_is_incomplete(
    rows: tuple[tuple[str, ...], ...],
) -> None:
    result = _normalize(
        _statement(
            ("Date", "Description", "Amount", "Balance"),
            *rows,
        )
    )

    assert result.balance_reconciled is None


@pytest.mark.parametrize(
    ("date_order", "value", "expected"),
    [
        (ImportDateOrder.DAY_FIRST, "20-08-2026", date(2026, 8, 20)),
        (ImportDateOrder.MONTH_FIRST, "08/20/2026", date(2026, 8, 20)),
        (ImportDateOrder.YEAR_FIRST, "2026.08.20", date(2026, 8, 20)),
        (ImportDateOrder.DAY_FIRST, "20 Aug 2026", date(2026, 8, 20)),
    ],
)
def test_date_orders_are_deterministic(
    date_order: ImportDateOrder,
    value: str,
    expected: date,
) -> None:
    result = _normalize(
        _statement(("Date", "Description", "Amount"), (value, "Entry", "1")),
        date_order=date_order,
    )

    assert result.rows[0].transaction_date == expected


@pytest.mark.parametrize(
    ("values", "code"),
    [
        (("", "Entry", "1"), ImportIssueCode.MISSING_DATE),
        (("31/02/2026", "Entry", "1"), ImportIssueCode.INVALID_DATE),
        (("21/08/2026", "Entry", "1"), ImportIssueCode.FUTURE_DATE),
        (("20/08/2026", "", "1"), ImportIssueCode.MISSING_DESCRIPTION),
        (("20/08/2026", "Entry", ""), ImportIssueCode.MISSING_AMOUNT),
        (("20/08/2026", "Entry", "0"), ImportIssueCode.ZERO_AMOUNT),
        (("20/08/2026", "Entry", "1.23456"), ImportIssueCode.INVALID_AMOUNT),
        (("20/08/2026", "Entry", "USD 10"), ImportIssueCode.INVALID_CURRENCY),
    ],
)
def test_invalid_rows_return_stable_non_sensitive_issues(
    values: tuple[str, str, str],
    code: ImportIssueCode,
) -> None:
    result = _normalize(
        _statement(("Date", "Description", "Amount"), values)
    )

    assert result.accepted_count == 0
    assert result.rejected_count == 1
    assert result.issues[0].code is code
    assert "USD 10" not in result.issues[0].message


def test_debit_credit_rejects_two_nonzero_values() -> None:
    result = _normalize(
        _statement(
            ("Date", "Description", "Debit", "Credit"),
            ("20/08/2026", "Ambiguous", "10", "20"),
        )
    )

    assert result.issues[0].code is ImportIssueCode.AMBIGUOUS_AMOUNT


def test_uncached_formula_in_required_cell_is_rejected() -> None:
    statement = _statement(
        ("Date", "Description", "Amount"),
        ("20/08/2026", "Calculated", None),
    )
    formula = ExtractedCell(None, formula_without_value=True)
    statement = ExtractedStatement(
        header=statement.header,
        rows=(
            ExtractedRow(
                row_number=2,
                cells=(statement.rows[0].cells[0], statement.rows[0].cells[1], formula),
            ),
        ),
    )

    result = _normalize(statement)

    assert result.issues[0].code is ImportIssueCode.UNCACHED_FORMULA


def test_blank_rows_are_ignored_during_reconciliation() -> None:
    result = _normalize(
        _statement(
            ("Date", "Description", "Amount"),
            ("", "", ""),
            ("20/08/2026", "Valid", "10"),
        )
    )

    assert result.accepted_count == 1
    assert result.rejected_count == 0


def test_issue_collection_is_bounded_without_losing_rejected_count() -> None:
    result = _normalize(
        _statement(
            ("Date", "Description", "Amount"),
            ("", "First", "1"),
            ("", "Second", "2"),
        ),
        max_issues=1,
    )

    assert result.rejected_count == 2
    assert len(result.issues) == 1
    assert result.issues_truncated is True


def test_reference_hash_rejects_in_file_and_existing_duplicates() -> None:
    statement = _statement(
        ("Date", "Description", "Amount", "Reference"),
        ("20/08/2026", "First", "10", "SAME-REF"),
        ("19/08/2026", "Second", "20", "same-ref"),
    )
    first = _normalize(
        _statement(
            ("Date", "Description", "Amount", "Reference"),
            ("20/08/2026", "First", "10", "SAME-REF"),
        )
    ).rows[0]

    in_file = _normalize(statement)
    existing = _normalize(statement, existing_hashes=frozenset({first.external_source_hash}))

    assert in_file.accepted_count == 1
    assert in_file.issues[0].code is ImportIssueCode.DUPLICATE_TRANSACTION
    assert existing.accepted_count == 0
    assert existing.rejected_count == 2


def test_identical_rows_without_reference_receive_occurrence_hashes() -> None:
    statement = _statement(
        ("Date", "Description", "Amount"),
        ("20/08/2026", "Same", "10"),
        ("20/08/2026", "Same", "10.00"),
    )

    first = _normalize(statement)
    second = _normalize(statement)

    assert first.accepted_count == 2
    assert first.rows[0].external_source_hash != first.rows[1].external_source_hash
    assert [row.external_source_hash for row in first.rows] == [
        row.external_source_hash for row in second.rows
    ]


def test_file_fingerprint_is_stable_and_content_sensitive() -> None:
    assert file_fingerprint(b"statement") == file_fingerprint(b"statement")
    assert file_fingerprint(b"statement") != file_fingerprint(b"Statement")
    assert len(file_fingerprint(b"statement")) == 64


def test_invalid_normalization_configuration_is_rejected() -> None:
    statement = _statement(
        ("Date", "Description", "Amount"),
        ("20/08/2026", "Entry", "1"),
    )

    with pytest.raises(ValueError, match="account_currency"):
        _normalize(statement, account_currency="rupees")
    with pytest.raises(ValueError, match="max_issues"):
        _normalize(statement, max_issues=-1)
