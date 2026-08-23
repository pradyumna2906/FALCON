"""Typed SQLAlchemy domain and authentication models."""

from falcon_api.models.account import Account, LiabilityDetail
from falcon_api.models.auth import (
    AuthenticationChallenge,
    AuthenticationDelivery,
    RefreshSession,
    RefreshToken,
    UserCredential,
)
from falcon_api.models.category import Category
from falcon_api.models.classification import TransactionClassification
from falcon_api.models.import_job import ImportJob, ImportJobIssue
from falcon_api.models.ledger import Transaction, TransferGroup
from falcon_api.models.planning import (
    Budget,
    BudgetLimit,
    Goal,
    GoalContribution,
)
from falcon_api.models.user import FinancialProfile, User


def register_models() -> None:
    """Ensure every model is imported into shared metadata."""


__all__ = [
    "Account",
    "AuthenticationChallenge",
    "AuthenticationDelivery",
    "Budget",
    "BudgetLimit",
    "Category",
    "FinancialProfile",
    "Goal",
    "GoalContribution",
    "ImportJob",
    "ImportJobIssue",
    "LiabilityDetail",
    "RefreshSession",
    "RefreshToken",
    "Transaction",
    "TransactionClassification",
    "TransferGroup",
    "User",
    "UserCredential",
    "register_models",
]
