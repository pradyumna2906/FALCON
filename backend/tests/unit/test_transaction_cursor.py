"""Unit contracts for integrity-protected transaction cursors."""

from datetime import date
from uuid import uuid4

import pytest
from falcon_api.models.enums import TransactionType
from falcon_api.transactions import (
    TransactionCursor,
    TransactionCursorCodec,
    TransactionFilters,
)
from falcon_api.transactions.cursor import InvalidTransactionCursorError


_SECRET = "transaction-cursor-test-secret-32-characters-minimum"


def test_cursor_round_trip_preserves_trusted_keyset() -> None:
    codec = TransactionCursorCodec(signing_secret=_SECRET)
    user_id = uuid4()
    filters = TransactionFilters(
        transaction_type=TransactionType.EXPENSE,
        date_from=date(2026, 8, 1),
    )
    expected = TransactionCursor(
        transaction_date=date(2026, 8, 20),
        transaction_id=uuid4(),
    )

    token = codec.encode(
        user_id=user_id,
        filters=filters,
        cursor=expected,
    )

    assert codec.decode(token, user_id=user_id, filters=filters) == expected
    assert len(token) <= 512


@pytest.mark.parametrize("mutation", ["payload", "signature", "format"])
def test_cursor_rejects_modified_or_malformed_tokens(mutation: str) -> None:
    codec = TransactionCursorCodec(signing_secret=_SECRET)
    user_id = uuid4()
    filters = TransactionFilters()
    token = codec.encode(
        user_id=user_id,
        filters=filters,
        cursor=TransactionCursor(date(2026, 8, 20), uuid4()),
    )
    payload, signature = token.split(".")
    mutated_payload_suffix = "B" if payload.endswith("A") else "A"
    mutated_signature_suffix = "B" if signature.endswith("A") else "A"
    candidates = {
        "payload": f"{payload[:-1]}{mutated_payload_suffix}.{signature}",
        "signature": f"{payload}.{signature[:-1]}{mutated_signature_suffix}",
        "format": "not-a-valid-cursor",
    }

    with pytest.raises(InvalidTransactionCursorError):
        codec.decode(
            candidates[mutation],
            user_id=user_id,
            filters=filters,
        )


def test_cursor_rejects_another_user_or_filter_set() -> None:
    codec = TransactionCursorCodec(signing_secret=_SECRET)
    user_id = uuid4()
    filters = TransactionFilters(account_id=uuid4())
    token = codec.encode(
        user_id=user_id,
        filters=filters,
        cursor=TransactionCursor(date(2026, 8, 20), uuid4()),
    )

    with pytest.raises(InvalidTransactionCursorError):
        codec.decode(token, user_id=uuid4(), filters=filters)
    with pytest.raises(InvalidTransactionCursorError):
        codec.decode(
            token,
            user_id=user_id,
            filters=TransactionFilters(account_id=uuid4()),
        )


def test_cursor_codec_requires_a_strong_secret() -> None:
    with pytest.raises(ValueError, match="at least 32"):
        TransactionCursorCodec(signing_secret="short")
