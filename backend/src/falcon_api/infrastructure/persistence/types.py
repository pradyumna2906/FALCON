"""Reusable annotated SQLAlchemy column mappings."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID, uuid4

from sqlalchemy import CHAR, DateTime, Numeric, Uuid
from sqlalchemy.orm import mapped_column


MONEY_PRECISION = 19
MONEY_SCALE = 4

RATE_PRECISION = 9
RATE_SCALE = 6

CURRENCY_CODE_LENGTH = 3


MoneyAmount = Annotated[
    Decimal,
    mapped_column(
        Numeric(
            precision=MONEY_PRECISION,
            scale=MONEY_SCALE,
            asdecimal=True,
        ),
    ),
]

RateValue = Annotated[
    Decimal,
    mapped_column(
        Numeric(
            precision=RATE_PRECISION,
            scale=RATE_SCALE,
            asdecimal=True,
        ),
    ),
]

CurrencyCode = Annotated[
    str,
    mapped_column(
        CHAR(length=CURRENCY_CODE_LENGTH),
    ),
]

UUIDPrimaryKey = Annotated[
    UUID,
    mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    ),
]

UTCDateTime = Annotated[
    datetime,
    mapped_column(
        DateTime(timezone=True),
    ),
]
