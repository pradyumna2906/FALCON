"""Typed SQLAlchemy domain models."""

from falcon_api.models.account import Account, LiabilityDetail
from falcon_api.models.category import Category
from falcon_api.models.import_job import ImportJob
from falcon_api.models.ledger import Transaction, TransferGroup
from falcon_api.models.planning import (
    Budget,
    BudgetLimit,
    Goal,
    GoalContribution,
)
from falcon_api.models.user import FinancialProfile, User


def register_models() -> None:
    """Ensure every domain model is imported into shared metadata."""


__all__ = [
    "Account",
    "Budget",
    "BudgetLimit",
    "Category",
    "FinancialProfile",
    "Goal",
    "GoalContribution",
    "ImportJob",
    "LiabilityDetail",
    "Transaction",
    "TransferGroup",
    "User",
    "register_models",
]
