"""Stable string-backed values used by FALCON domain models."""

from enum import StrEnum
from typing import TypeVar


class UserStatus(StrEnum):
    """Persistent user lifecycle states."""

    ACTIVE = "active"
    DISABLED = "disabled"


class ProfileCompletionStatus(StrEnum):
    """Financial-profile completion states."""

    DRAFT = "draft"
    COMPLETE = "complete"


class IncomePattern(StrEnum):
    """Supported income patterns."""

    SALARIED = "salaried"
    SELF_EMPLOYED = "self_employed"
    IRREGULAR = "irregular"
    MIXED = "mixed"


class IncomeStability(StrEnum):
    """Supported income-stability assessments."""

    STABLE = "stable"
    VARIABLE = "variable"
    UNSTABLE = "unstable"


class AccountType(StrEnum):
    """Supported financial account types."""

    BANK = "bank"
    CASH = "cash"
    WALLET = "wallet"
    CREDIT_CARD = "credit_card"
    INVESTMENT = "investment"
    LOAN = "loan"


class LiabilitySubtype(StrEnum):
    """Supported liability specializations."""

    LOAN = "loan"
    CREDIT_CARD = "credit_card"


class CategoryKind(StrEnum):
    """Supported transaction category meanings."""

    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER = "transfer"


class ImportSourceType(StrEnum):
    """Supported statement-import sources."""

    CSV = "csv"
    EXCEL = "excel"
    BANK_STATEMENT = "bank_statement"
    CREDIT_CARD_STATEMENT = "credit_card_statement"
    PAYTM = "paytm"
    PHONEPE = "phonepe"
    GOOGLE_PAY = "google_pay"


class ImportStatus(StrEnum):
    """Import processing lifecycle states."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class TransactionType(StrEnum):
    """Supported transaction meanings."""

    INCOME = "income"
    EXPENSE = "expense"
    TRANSFER = "transfer"
    ADJUSTMENT = "adjustment"


class TransactionStatus(StrEnum):
    """Supported transaction posting states."""

    PENDING = "pending"
    POSTED = "posted"


class TransactionSourceType(StrEnum):
    """Supported transaction provenance types."""

    MANUAL = "manual"
    IMPORT = "import"
    TRANSFER = "transfer"
    ADJUSTMENT = "adjustment"


class GoalType(StrEnum):
    """Supported financial goal types."""

    TRAVEL = "travel"
    MARRIAGE = "marriage"
    EDUCATION = "education"
    EMERGENCY_FUND = "emergency_fund"
    MAJOR_PURCHASE = "major_purchase"
    OTHER = "other"


class GoalPriority(StrEnum):
    """Supported goal priorities."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class GoalStatus(StrEnum):
    """Supported goal lifecycle states."""

    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ContributionSourceType(StrEnum):
    """Supported goal-contribution sources."""

    MANUAL = "manual"
    TRANSACTION = "transaction"
    OPENING_BALANCE = "opening_balance"

class AuthenticationChallengePurpose(StrEnum):
    """Supported single-use authentication challenge purposes."""

    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"


class AuthenticationDeliveryStatus(StrEnum):
    """Durable authentication-message delivery states."""

    PENDING = "pending"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"

_EnumType = TypeVar("_EnumType", bound=StrEnum)


def enum_sql_values(enum_type: type[_EnumType]) -> str:
    """Return safely quoted SQL literals for a closed internal enum."""
    return ", ".join(f"'{member.value}'" for member in enum_type)
