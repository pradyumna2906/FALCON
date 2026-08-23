"""Deterministic shared features for classification training and inference."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from falcon_api.models.enums import TransactionType


CLASSIFICATION_FEATURE_SCHEMA_VERSION = "2026.1"
MAX_DESCRIPTION_TOKENS = 64
MAX_MERCHANT_TOKENS = 8


class PaymentChannel(StrEnum):
    """Deterministic payment-rail signal extracted from statement text."""

    UPI = "upi"
    IMPS = "imps"
    NEFT = "neft"
    RTGS = "rtgs"
    CARD = "card"
    ATM = "atm"
    ACH = "ach"
    CHEQUE = "cheque"
    WALLET = "wallet"
    CASH = "cash"
    BANK_TRANSFER = "bank_transfer"
    UNKNOWN = "unknown"


class AmountBand(StrEnum):
    """Coarse magnitude bands that avoid memorizing exact user amounts."""

    MICRO = "micro"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    VERY_LARGE = "very_large"


@dataclass(frozen=True, slots=True)
class TransactionFeatureInput:
    """Trusted canonical ledger values accepted by the feature builder."""

    description: str
    merchant_name: str | None
    transaction_type: TransactionType
    signed_amount: Decimal
    transaction_date: date
    account_currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.description, str) or not self.description.strip():
            raise ValueError("description must be non-blank.")
        if len(self.description) > 500:
            raise ValueError("description exceeds the ledger limit.")
        if self.merchant_name is not None:
            if not isinstance(self.merchant_name, str):
                raise TypeError("merchant_name must be text or None.")
            if len(self.merchant_name) > 200:
                raise ValueError("merchant_name exceeds the ledger limit.")
        if not isinstance(self.transaction_type, TransactionType):
            raise TypeError("transaction_type must be a TransactionType.")
        if not isinstance(self.signed_amount, Decimal):
            raise TypeError("signed_amount must be an exact Decimal.")
        if not self.signed_amount.is_finite() or self.signed_amount == 0:
            raise ValueError("signed_amount must be finite and non-zero.")
        if (
            self.transaction_type is TransactionType.INCOME
            and self.signed_amount < 0
        ):
            raise ValueError("Income requires a positive ledger amount.")
        if (
            self.transaction_type is TransactionType.EXPENSE
            and self.signed_amount > 0
        ):
            raise ValueError("Expense requires a negative ledger amount.")
        if type(self.transaction_date) is not date:
            raise TypeError("transaction_date must be a calendar date.")
        if not isinstance(self.account_currency, str):
            raise TypeError("account_currency must be text.")
        if re.fullmatch(r"[A-Z]{3}", self.account_currency) is None:
            raise ValueError("account_currency must be an uppercase ISO-style code.")


@dataclass(frozen=True, slots=True)
class ClassificationFeatures:
    """Versioned, model-ready values shared by training and inference."""

    schema_version: str
    normalized_description: str
    description_tokens: tuple[str, ...]
    normalized_merchant: str | None
    payment_channel: PaymentChannel
    transaction_type: TransactionType
    account_currency: str
    amount_band: AmountBand
    month: int
    day_of_month: int
    weekday: int
    is_weekend: bool
    is_recurring_candidate: bool


_WHITESPACE = re.compile(r"\s+")
_PUNCTUATION = re.compile(r"[^\w]+", re.UNICODE)
_UPI_OR_EMAIL_ID = re.compile(
    r"(?<!\w)[\w.+-]{2,}@[a-z0-9.-]{2,}(?!\w)",
    re.IGNORECASE,
)
_MASKED_ACCOUNT = re.compile(
    r"(?<!\w)(?:x{2,}|\*{2,})\s*\d{2,}(?!\w)",
    re.IGNORECASE,
)
_LONG_DIGIT_REFERENCE = re.compile(r"(?<!\w)\d{4,}(?!\w)")
_NUMERIC_VALUE = re.compile(r"(?<!\w)\d+(?:[.,]\d+)?(?!\w)")
_ALPHANUMERIC_REFERENCE = re.compile(
    r"(?<!\w)(?=[a-z0-9]{10,}(?!\w))(?=[a-z0-9]*[a-z])"
    r"(?=[a-z0-9]*\d)[a-z0-9]+",
    re.IGNORECASE,
)
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")

_CHANNEL_PATTERNS = (
    (PaymentChannel.UPI, re.compile(r"\bupi\b", re.IGNORECASE)),
    (PaymentChannel.IMPS, re.compile(r"\bimps\b", re.IGNORECASE)),
    (PaymentChannel.NEFT, re.compile(r"\bneft\b", re.IGNORECASE)),
    (PaymentChannel.RTGS, re.compile(r"\brtgs\b", re.IGNORECASE)),
    (
        PaymentChannel.ATM,
        re.compile(r"\b(?:atm|cash\s+withdrawal)\b", re.IGNORECASE),
    ),
    (
        PaymentChannel.CARD,
        re.compile(
            r"\b(?:pos|card|debit\s+card|credit\s+card|ecom)\b",
            re.IGNORECASE,
        ),
    ),
    (
        PaymentChannel.ACH,
        re.compile(r"\b(?:ach|nach|ecs|autopay)\b", re.IGNORECASE),
    ),
    (
        PaymentChannel.CHEQUE,
        re.compile(r"\b(?:cheque|check|chq)\b", re.IGNORECASE),
    ),
    (
        PaymentChannel.WALLET,
        re.compile(r"\b(?:wallet|paytm|phonepe|google\s+pay)\b", re.IGNORECASE),
    ),
    (PaymentChannel.CASH, re.compile(r"\bcash\b", re.IGNORECASE)),
    (
        PaymentChannel.BANK_TRANSFER,
        re.compile(r"\bbank\s+transfer\b", re.IGNORECASE),
    ),
)

_NOISE_TOKENS = frozenset(
    {
        "ach",
        "aed",
        "atm",
        "aud",
        "bank",
        "cad",
        "card",
        "chq",
        "cr",
        "credit",
        "cny",
        "debit",
        "dr",
        "eur",
        "gbp",
        "ecom",
        "ecs",
        "imps",
        "inr",
        "jpy",
        "nach",
        "neft",
        "no",
        "number",
        "online",
        "order",
        "paid",
        "payment",
        "pos",
        "purchase",
        "ref",
        "reference",
        "rtgs",
        "sgd",
        "to",
        "transaction",
        "transfer",
        "txn",
        "upi",
        "usd",
        "via",
    }
)
_MERCHANT_NOISE_TOKENS = _NOISE_TOKENS | {
    "at",
    "by",
    "from",
    "india",
    "merchant",
}
_RECURRING_PATTERN = re.compile(
    r"\b(?:autopay|emi|ecs|insurance\s+premium|monthly|nach|rent|salary|sip|"
    r"standing\s+instruction|subscription)\b",
    re.IGNORECASE,
)
_MERCHANT_INFERENCE_CHANNELS = frozenset(
    {
        PaymentChannel.UPI,
        PaymentChannel.IMPS,
        PaymentChannel.NEFT,
        PaymentChannel.RTGS,
        PaymentChannel.CARD,
        PaymentChannel.WALLET,
        PaymentChannel.BANK_TRANSFER,
    }
)


def build_classification_features(
    transaction: TransactionFeatureInput,
) -> ClassificationFeatures:
    """Build one deterministic feature object from canonical ledger facts."""
    folded_description = _fold_text(transaction.description)
    payment_channel = detect_payment_channel(folded_description)
    description_tokens = _safe_tokens(
        folded_description,
        noise_tokens=_NOISE_TOKENS,
        limit=MAX_DESCRIPTION_TOKENS,
    )
    normalized_description = " ".join(description_tokens)
    normalized_merchant = normalize_merchant(transaction.merchant_name)
    if normalized_merchant is None and payment_channel in _MERCHANT_INFERENCE_CHANNELS:
        normalized_merchant = _infer_merchant(folded_description)

    magnitude = transaction.signed_amount.copy_abs()
    transaction_date = transaction.transaction_date
    return ClassificationFeatures(
        schema_version=CLASSIFICATION_FEATURE_SCHEMA_VERSION,
        normalized_description=normalized_description,
        description_tokens=description_tokens,
        normalized_merchant=normalized_merchant,
        payment_channel=payment_channel,
        transaction_type=transaction.transaction_type,
        account_currency=transaction.account_currency,
        amount_band=amount_band(magnitude),
        month=transaction_date.month,
        day_of_month=transaction_date.day,
        weekday=transaction_date.weekday(),
        is_weekend=transaction_date.weekday() >= 5,
        is_recurring_candidate=bool(_RECURRING_PATTERN.search(folded_description)),
    )


def feature_record(features: ClassificationFeatures) -> dict[str, str | int | bool]:
    """Return a stable primitive record for both training and inference."""
    return {
        "schema_version": features.schema_version,
        "normalized_description": features.normalized_description,
        "normalized_merchant": features.normalized_merchant or "",
        "payment_channel": features.payment_channel.value,
        "transaction_type": features.transaction_type.value,
        "account_currency": features.account_currency,
        "amount_band": features.amount_band.value,
        "month": features.month,
        "day_of_month": features.day_of_month,
        "weekday": features.weekday,
        "is_weekend": features.is_weekend,
        "is_recurring_candidate": features.is_recurring_candidate,
    }


def detect_payment_channel(text: str) -> PaymentChannel:
    """Return the first reviewed payment-rail marker in priority order."""
    folded = _fold_text(text)
    for channel, pattern in _CHANNEL_PATTERNS:
        if pattern.search(folded):
            return channel
    return PaymentChannel.UNKNOWN


def normalize_merchant(value: str | None) -> str | None:
    """Normalize an explicit merchant without applying alias knowledge."""
    if value is None or not value.strip():
        return None
    tokens = _safe_tokens(
        _fold_text(value),
        noise_tokens=_MERCHANT_NOISE_TOKENS,
        limit=MAX_MERCHANT_TOKENS,
    )
    return " ".join(tokens) or None


def amount_band(magnitude: Decimal) -> AmountBand:
    """Map a positive exact magnitude into the reviewed coarse band."""
    if not isinstance(magnitude, Decimal):
        raise TypeError("magnitude must be an exact Decimal.")
    if not magnitude.is_finite() or magnitude <= 0:
        raise ValueError("magnitude must be finite and positive.")
    if magnitude <= Decimal("100"):
        return AmountBand.MICRO
    if magnitude <= Decimal("1000"):
        return AmountBand.SMALL
    if magnitude <= Decimal("5000"):
        return AmountBand.MEDIUM
    if magnitude <= Decimal("25000"):
        return AmountBand.LARGE
    return AmountBand.VERY_LARGE


def _fold_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return _WHITESPACE.sub(" ", _CONTROL_CHARACTERS.sub(" ", normalized)).strip()


def _safe_tokens(
    folded_text: str,
    *,
    noise_tokens: frozenset[str],
    limit: int,
) -> tuple[str, ...]:
    masked = _UPI_OR_EMAIL_ID.sub(" ref ", folded_text)
    masked = _MASKED_ACCOUNT.sub(" ref ", masked)
    masked = _ALPHANUMERIC_REFERENCE.sub(" ref ", masked)
    masked = _LONG_DIGIT_REFERENCE.sub(" ref ", masked)
    masked = _NUMERIC_VALUE.sub(" ref ", masked)
    normalized = _PUNCTUATION.sub(" ", masked)
    tokens = (
        token
        for token in normalized.split()
        if token not in noise_tokens and token != "ref"
    )
    return tuple(tokens)[:limit]


def _infer_merchant(folded_description: str) -> str | None:
    tokens = _safe_tokens(
        folded_description,
        noise_tokens=_MERCHANT_NOISE_TOKENS,
        limit=MAX_MERCHANT_TOKENS,
    )
    return " ".join(tokens) or None
