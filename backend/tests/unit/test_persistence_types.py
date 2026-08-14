"""Reusable financial persistence type tests."""

from decimal import Decimal

from falcon_api.infrastructure.persistence import (
    CURRENCY_CODE_LENGTH,
    MONEY_PRECISION,
    MONEY_SCALE,
    RATE_PRECISION,
    RATE_SCALE,
    CurrencyCode,
    MoneyAmount,
    RateValue,
    UTCDateTime,
    UUIDPrimaryKey,
    create_metadata,
)
from sqlalchemy.orm import DeclarativeBase, Mapped


class _TestBase(DeclarativeBase):
    metadata = create_metadata()


class _FinancialTypeModel(_TestBase):
    __tablename__ = "financial_type_examples"

    id: Mapped[UUIDPrimaryKey]
    amount: Mapped[MoneyAmount]
    rate: Mapped[RateValue]
    currency: Mapped[CurrencyCode]
    occurred_at: Mapped[UTCDateTime]


def test_money_mapping_uses_exact_approved_numeric_type() -> None:
    column_type = _FinancialTypeModel.__table__.c.amount.type

    assert column_type.precision == MONEY_PRECISION == 19
    assert column_type.scale == MONEY_SCALE == 4
    assert column_type.asdecimal is True
    assert column_type.python_type is Decimal


def test_rate_mapping_uses_exact_approved_numeric_type() -> None:
    column_type = _FinancialTypeModel.__table__.c.rate.type

    assert column_type.precision == RATE_PRECISION == 9
    assert column_type.scale == RATE_SCALE == 6
    assert column_type.asdecimal is True
    assert column_type.python_type is Decimal


def test_currency_mapping_has_fixed_three_character_length() -> None:
    column_type = _FinancialTypeModel.__table__.c.currency.type

    assert column_type.length == CURRENCY_CODE_LENGTH == 3
    assert column_type.python_type is str


def test_uuid_mapping_uses_native_uuid_objects() -> None:
    column_type = _FinancialTypeModel.__table__.c.id.type

    assert column_type.as_uuid is True


def test_timestamp_mapping_is_timezone_aware() -> None:
    column_type = _FinancialTypeModel.__table__.c.occurred_at.type

    assert column_type.timezone is True
