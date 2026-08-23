"""Tests for deterministic Phase 7 classification feature construction."""

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

import pytest
from falcon_api.classification.features import (
    CLASSIFICATION_FEATURE_SCHEMA_VERSION,
    MAX_DESCRIPTION_TOKENS,
    AmountBand,
    PaymentChannel,
    TransactionFeatureInput,
    amount_band,
    build_classification_features,
    classification_model_text,
    detect_payment_channel,
    feature_record,
    normalize_merchant,
)
from falcon_api.models.enums import TransactionType


def _input(
    *,
    description: str = "UPI/123456789012/SWIGGY/order@okhdfcbank",
    merchant_name: str | None = None,
    transaction_type: TransactionType = TransactionType.EXPENSE,
    signed_amount: Decimal = Decimal("-850.00"),
    transaction_date: date = date(2026, 8, 23),
    account_currency: str = "INR",
) -> TransactionFeatureInput:
    return TransactionFeatureInput(
        description=description,
        merchant_name=merchant_name,
        transaction_type=transaction_type,
        signed_amount=signed_amount,
        transaction_date=transaction_date,
        account_currency=account_currency,
    )


def test_upi_features_mask_references_and_infer_merchant() -> None:
    features = build_classification_features(_input())

    assert features.schema_version == CLASSIFICATION_FEATURE_SCHEMA_VERSION
    assert features.payment_channel is PaymentChannel.UPI
    assert features.normalized_description == "swiggy"
    assert features.description_tokens == ("swiggy",)
    assert features.normalized_merchant == "swiggy"
    assert "123456789012" not in features.normalized_description
    assert "okhdfcbank" not in features.normalized_description


def test_explicit_merchant_is_preferred_without_alias_guessing() -> None:
    features = build_classification_features(
        _input(
            description="POS 492912345678 AMAZON MARKETPLACE",
            merchant_name="  Amazon   India  ",
        )
    )

    assert features.payment_channel is PaymentChannel.CARD
    assert features.normalized_merchant == "amazon"
    assert features.normalized_description == "amazon marketplace"


def test_unknown_free_text_does_not_invent_a_merchant() -> None:
    features = build_classification_features(
        _input(description="Monthly apartment rent")
    )

    assert features.payment_channel is PaymentChannel.UNKNOWN
    assert features.normalized_merchant is None
    assert features.is_recurring_candidate is True


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("UPI payment", PaymentChannel.UPI),
        ("IMPS transfer", PaymentChannel.IMPS),
        ("NEFT credit", PaymentChannel.NEFT),
        ("RTGS transfer", PaymentChannel.RTGS),
        ("POS purchase", PaymentChannel.CARD),
        ("ATM cash withdrawal", PaymentChannel.ATM),
        ("NACH debit", PaymentChannel.ACH),
        ("CHQ deposit", PaymentChannel.CHEQUE),
        ("Paytm wallet", PaymentChannel.WALLET),
        ("cash purchase", PaymentChannel.CASH),
        ("bank transfer", PaymentChannel.BANK_TRANSFER),
        ("ordinary description", PaymentChannel.UNKNOWN),
    ],
)
def test_payment_channels_are_detected_deterministically(
    description: str,
    expected: PaymentChannel,
) -> None:
    assert detect_payment_channel(description) is expected


def test_channel_priority_is_stable_for_multiple_markers() -> None:
    assert detect_payment_channel("UPI funded by card") is PaymentChannel.UPI
    assert detect_payment_channel("ATM cash withdrawal") is PaymentChannel.ATM


def test_unicode_and_control_characters_are_normalized() -> None:
    features = build_classification_features(
        _input(description="ＵＰＩ\x00 Café—Déjà  123456")
    )

    assert features.payment_channel is PaymentChannel.UPI
    assert features.normalized_description == "café déjà"


def test_reference_shapes_are_not_present_in_model_record() -> None:
    features = build_classification_features(
        _input(
            description=(
                "NEFT HDFC000123456 ACME SERVICES "
                "person.name@example.com XXXX4321 paid INR 849.99"
            )
        )
    )
    record = feature_record(features)

    assert features.normalized_merchant == "acme services"
    serialized = " ".join(str(value) for value in record.values())
    assert "hdfc000123456" not in serialized
    assert "example.com" not in serialized
    assert "4321" not in serialized
    assert "849" not in serialized


@pytest.mark.parametrize(
    ("magnitude", "expected"),
    [
        (Decimal("0.01"), AmountBand.MICRO),
        (Decimal("100"), AmountBand.MICRO),
        (Decimal("100.01"), AmountBand.SMALL),
        (Decimal("1000"), AmountBand.SMALL),
        (Decimal("1000.01"), AmountBand.MEDIUM),
        (Decimal("5000"), AmountBand.MEDIUM),
        (Decimal("5000.01"), AmountBand.LARGE),
        (Decimal("25000"), AmountBand.LARGE),
        (Decimal("25000.01"), AmountBand.VERY_LARGE),
    ],
)
def test_amount_band_boundaries_are_exact(
    magnitude: Decimal,
    expected: AmountBand,
) -> None:
    assert amount_band(magnitude) is expected


@pytest.mark.parametrize("invalid", [Decimal("0"), Decimal("-1"), Decimal("NaN")])
def test_amount_band_rejects_invalid_magnitudes(invalid: Decimal) -> None:
    with pytest.raises(ValueError):
        amount_band(invalid)


def test_amount_band_requires_decimal() -> None:
    with pytest.raises(TypeError):
        amount_band(100)  # type: ignore[arg-type]


def test_calendar_and_direction_features_come_from_canonical_ledger() -> None:
    features = build_classification_features(
        _input(
            description="Salary monthly",
            transaction_type=TransactionType.INCOME,
            signed_amount=Decimal("50000"),
            transaction_date=date(2026, 8, 23),
        )
    )

    assert features.transaction_type is TransactionType.INCOME
    assert features.account_currency == "INR"
    assert features.amount_band is AmountBand.VERY_LARGE
    assert (features.month, features.day_of_month, features.weekday) == (8, 23, 6)
    assert features.is_weekend is True
    assert features.is_recurring_candidate is True


def test_feature_record_has_stable_shared_training_and_inference_shape() -> None:
    features = build_classification_features(_input())

    assert list(feature_record(features)) == [
        "schema_version",
        "normalized_description",
        "normalized_merchant",
        "payment_channel",
        "transaction_type",
        "account_currency",
        "amount_band",
        "month",
        "day_of_month",
        "weekday",
        "is_weekend",
        "is_recurring_candidate",
    ]
    assert feature_record(features) == feature_record(features)


def test_model_text_is_shared_by_training_and_inference() -> None:
    features = build_classification_features(_input())

    assert classification_model_text(features) == (
        "swiggy swiggy type_expense channel_upi amount_small currency_inr "
        "month_8 weekday_6 weekend_1 recurring_0"
    )


def test_model_text_rejects_invalid_or_incompatible_features() -> None:
    with pytest.raises(TypeError):
        classification_model_text("unsafe")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="feature-schema"):
        classification_model_text(
            replace(build_classification_features(_input()), schema_version="old")
        )


def test_description_token_count_is_bounded() -> None:
    description = " ".join(f"w{index}" for index in range(80))
    features = build_classification_features(_input(description=description))

    assert len(features.description_tokens) == MAX_DESCRIPTION_TOKENS
    assert features.description_tokens[-1] == "w63"


def test_normalize_merchant_handles_blank_and_sensitive_references() -> None:
    assert normalize_merchant(None) is None
    assert normalize_merchant("   ") is None
    assert normalize_merchant("MERCHANT ACME XXXX4321 INDIA") == "acme"


@pytest.mark.parametrize(
    "overrides",
    [
        {"description": " "},
        {"description": "x" * 501},
        {"merchant_name": "x" * 201},
        {"merchant_name": 123},
        {"transaction_type": "expense"},
        {"signed_amount": -1},
        {"signed_amount": Decimal("0")},
        {"signed_amount": Decimal("Infinity")},
        {
            "transaction_type": TransactionType.INCOME,
            "signed_amount": Decimal("-1"),
        },
        {
            "transaction_type": TransactionType.EXPENSE,
            "signed_amount": Decimal("1"),
        },
        {"transaction_date": datetime(2026, 8, 23, 10, 0)},
        {"account_currency": "inr"},
        {"account_currency": "RUPEE"},
        {"account_currency": 356},
    ],
)
def test_feature_input_rejects_invalid_ledger_values(
    overrides: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "description": "Valid entry",
        "merchant_name": None,
        "transaction_type": TransactionType.EXPENSE,
        "signed_amount": Decimal("-1"),
        "transaction_date": date(2026, 8, 23),
        "account_currency": "INR",
    }
    values.update(overrides)

    with pytest.raises((TypeError, ValueError)):
        TransactionFeatureInput(**values)  # type: ignore[arg-type]


def test_manual_and_imported_equivalents_produce_identical_features() -> None:
    manual = _input(
        description="UPI/9876543210/SWIGGY/order@oksbi",
        merchant_name="Swiggy",
    )
    imported = _input(
        description="UPI/1234567890/SWIGGY/food@okhdfcbank",
        merchant_name="Swiggy",
    )

    manual_features = build_classification_features(manual)
    imported_features = build_classification_features(imported)

    assert manual_features.normalized_merchant == imported_features.normalized_merchant
    assert manual_features.payment_channel == imported_features.payment_channel
    assert manual_features.amount_band == imported_features.amount_band
