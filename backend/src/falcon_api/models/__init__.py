"""Typed SQLAlchemy domain and authentication models."""

from falcon_api.models.account import Account, LiabilityDetail
from falcon_api.models.assistant import (
    AssistantKnowledgeChunk,
    AssistantKnowledgeDocument,
)
from falcon_api.models.auth import (
    AuthenticationChallenge,
    AuthenticationDelivery,
    RefreshSession,
    RefreshToken,
    UserCredential,
)
from falcon_api.models.category import Category
from falcon_api.models.classification import (
    TransactionCategoryCorrection,
    TransactionClassification,
    UserMerchantMemory,
)
from falcon_api.models.forecasting import ForecastPoint, ForecastRun
from falcon_api.models.goal_plan import (
    GoalPlanAllocation,
    GoalPlanEvent,
    GoalPlanOutcome,
    GoalPlanPeriod,
    GoalPlanRun,
)
from falcon_api.models.import_job import ImportJob, ImportJobIssue
from falcon_api.models.ledger import Transaction, TransferGroup
from falcon_api.models.planning import (
    Budget,
    BudgetLimit,
    Goal,
    GoalContribution,
)
from falcon_api.models.scenario import (
    ScenarioComparison,
    ScenarioDefinition,
    ScenarioEvent,
    ScenarioGoalOutcome,
    ScenarioPeriod,
    ScenarioSimulationRun,
)
from falcon_api.models.user import FinancialProfile, User


def register_models() -> None:
    """Ensure every model is imported into shared metadata."""


__all__ = [
    "Account",
    "AuthenticationChallenge",
    "AuthenticationDelivery",
    "AssistantKnowledgeChunk",
    "AssistantKnowledgeDocument",
    "Budget",
    "BudgetLimit",
    "Category",
    "FinancialProfile",
    "ForecastPoint",
    "ForecastRun",
    "Goal",
    "GoalContribution",
    "GoalPlanAllocation",
    "GoalPlanEvent",
    "GoalPlanOutcome",
    "GoalPlanPeriod",
    "GoalPlanRun",
    "ImportJob",
    "ImportJobIssue",
    "LiabilityDetail",
    "RefreshSession",
    "RefreshToken",
    "ScenarioComparison",
    "ScenarioDefinition",
    "ScenarioEvent",
    "ScenarioGoalOutcome",
    "ScenarioPeriod",
    "ScenarioSimulationRun",
    "Transaction",
    "TransactionCategoryCorrection",
    "TransactionClassification",
    "TransferGroup",
    "User",
    "UserCredential",
    "UserMerchantMemory",
    "register_models",
]
