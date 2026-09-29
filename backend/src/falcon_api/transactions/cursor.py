"""Integrity-protected transaction timeline cursors."""

import base64
import binascii
import hashlib
import hmac
import json
from datetime import date
from uuid import UUID

from falcon_api.transactions.repository import (
    TransactionCursor,
    TransactionFilters,
)


class InvalidTransactionCursorError(ValueError):
    """Signal an invalid, mismatched, or modified cursor."""


class TransactionCursorCodec:
    """Encode and validate opaque user-and-filter-bound keysets."""

    def __init__(self, *, signing_secret: str) -> None:
        if len(signing_secret) < 32:
            raise ValueError(
                "The cursor signing secret must contain at least 32 characters."
            )
        secret = signing_secret.encode("utf-8")
        self._signing_key = hmac.new(
            secret,
            b"falcon-transaction-cursor-signing-v1",
            hashlib.sha256,
        ).digest()
        self._binding_key = hmac.new(
            secret,
            b"falcon-transaction-cursor-binding-v1",
            hashlib.sha256,
        ).digest()

    def encode(
        self,
        *,
        user_id: UUID,
        filters: TransactionFilters,
        cursor: TransactionCursor,
    ) -> str:
        """Encode one trusted keyset position as a signed token."""
        payload = {
            "d": cursor.transaction_date.isoformat(),
            "f": self._filter_binding(filters),
            "i": str(cursor.transaction_id),
            "u": self._user_binding(user_id),
            "v": 1,
        }
        serialized = json.dumps(
            payload,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        encoded_payload = _encode(serialized)
        signature = hmac.new(
            self._signing_key,
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return f"{encoded_payload}.{_encode(signature)}"

    def decode(
        self,
        token: str,
        *,
        user_id: UUID,
        filters: TransactionFilters,
    ) -> TransactionCursor:
        """Validate a cursor and return its trusted typed keyset."""
        try:
            encoded_payload, encoded_signature = token.split(".")
            signature = _decode(encoded_signature)
            expected_signature = hmac.new(
                self._signing_key,
                encoded_payload.encode("ascii"),
                hashlib.sha256,
            ).digest()
            if not hmac.compare_digest(signature, expected_signature):
                raise InvalidTransactionCursorError

            payload = json.loads(_decode(encoded_payload))
            if not isinstance(payload, dict) or set(payload) != {
                "d",
                "f",
                "i",
                "u",
                "v",
            }:
                raise InvalidTransactionCursorError
            if payload["v"] != 1:
                raise InvalidTransactionCursorError
            if not hmac.compare_digest(
                str(payload["u"]),
                self._user_binding(user_id),
            ):
                raise InvalidTransactionCursorError
            if not hmac.compare_digest(
                str(payload["f"]),
                self._filter_binding(filters),
            ):
                raise InvalidTransactionCursorError

            return TransactionCursor(
                transaction_date=date.fromisoformat(payload["d"]),
                transaction_id=UUID(payload["i"]),
            )
        except InvalidTransactionCursorError:
            raise
        except (
            AttributeError,
            binascii.Error,
            json.JSONDecodeError,
            TypeError,
            UnicodeDecodeError,
            ValueError,
        ) as exc:
            raise InvalidTransactionCursorError from exc

    def _user_binding(self, user_id: UUID) -> str:
        return hmac.new(
            self._binding_key,
            str(user_id).encode("ascii"),
            hashlib.sha256,
        ).hexdigest()

    def _filter_binding(self, filters: TransactionFilters) -> str:
        values = {
            "account_id": _optional_text(filters.account_id),
            "category_id": _optional_text(filters.category_id),
            "date_from": _optional_text(filters.date_from),
            "date_to": _optional_text(filters.date_to),
            "status": _optional_text(filters.status),
            "transaction_type": _optional_text(filters.transaction_type),
        }
        serialized = json.dumps(
            values,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hmac.new(
            self._binding_key,
            serialized,
            hashlib.sha256,
        ).hexdigest()


def _optional_text(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    decoded = base64.b64decode(
        value + padding,
        altchars=b"-_",
        validate=True,
    )
    if _encode(decoded) != value:
        raise InvalidTransactionCursorError
    return decoded
