"""Versioned Phase 12 grounded-assistant boundaries."""

from enum import StrEnum


ASSISTANT_CONTRACT_VERSION = "2026.1"
ASSISTANT_PRIVACY_POLICY_VERSION = "2026.1"
ASSISTANT_SAFETY_POLICY_VERSION = "2026.1"

MAX_QUESTION_CHARACTERS = 2_000
MAX_ANSWER_CHARACTERS = 12_000
MAX_EVIDENCE_SUMMARIES = 20
MAX_EVIDENCE_SUMMARY_CHARACTERS = 500
MAX_CITATIONS = 20
MAX_CITATION_LABEL_CHARACTERS = 160
MAX_SOURCE_REFERENCE_CHARACTERS = 128
MAX_SUGGESTED_QUESTIONS = 5
MAX_SUGGESTED_QUESTION_CHARACTERS = 300
MAX_PROMPT_TEXT_CHARACTERS = 8_000
MAX_PROMPT_COLLECTION_ITEMS = 500
MAX_PROMPT_NESTING_DEPTH = 6


class AssistantIntent(StrEnum):
    """Closed user intents supported by the first grounded assistant."""

    EXPLAIN_DASHBOARD = "explain_dashboard"
    EXPLAIN_FINANCIAL_HEALTH = "explain_financial_health"
    SUMMARIZE_SPENDING = "summarize_spending"
    EXPLAIN_SPENDING_SIGNAL = "explain_spending_signal"
    EXPLAIN_FORECAST = "explain_forecast"
    EXPLAIN_GOAL_PROGRESS = "explain_goal_progress"
    EXPLAIN_GOAL_PLAN = "explain_goal_plan"
    COMPARE_SCENARIOS = "compare_scenarios"
    FINANCIAL_EDUCATION = "financial_education"
    UNSUPPORTED = "unsupported"


class AssistantAnswerStatus(StrEnum):
    """Public disposition of one assistant answer."""

    ANSWERED = "answered"
    LIMITED = "limited"
    UNAVAILABLE = "unavailable"
    REFUSED = "refused"


class AssistantReliability(StrEnum):
    """Worst evidence reliability carried into a generated answer."""

    NORMAL = "normal"
    PROVISIONAL = "provisional"
    CONSERVATIVE = "conservative"
    UNAVAILABLE = "unavailable"


class AssistantEvidenceSource(StrEnum):
    """Closed source families that may contribute assistant evidence."""

    ANALYTICS = "analytics"
    FORECAST = "forecast"
    GOAL_PROGRESS = "goal_progress"
    GOAL_PLAN = "goal_plan"
    SCENARIO_SIMULATION = "scenario_simulation"
    KNOWLEDGE = "knowledge"


class AssistantWarning(StrEnum):
    """Bounded warnings safe to expose with an assistant answer."""

    EVIDENCE_PROVISIONAL = "evidence_provisional"
    EVIDENCE_CONSERVATIVE = "evidence_conservative"
    EVIDENCE_INCOMPLETE = "evidence_incomplete"
    EVIDENCE_STALE = "evidence_stale"
    POLICY_LIMITATION = "policy_limitation"
    NOT_FINANCIAL_ADVICE = "not_financial_advice"


class AssistantRefusalReason(StrEnum):
    """Closed public reasons for withholding a generated answer."""

    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    UNSUPPORTED_REQUEST = "unsupported_request"
    PROHIBITED_FINANCIAL_ACTION = "prohibited_financial_action"
    PRODUCT_SPECIFIC_INVESTMENT_ADVICE = "product_specific_investment_advice"
    GUARANTEED_OUTCOME = "guaranteed_outcome"
    PROMPT_INJECTION = "prompt_injection"
    DATA_EXFILTRATION = "data_exfiltration"
    AUTHORIZATION_REQUIRED = "authorization_required"


class AssistantThreat(StrEnum):
    """Threats that require explicit Phase 12 controls and tests."""

    CROSS_OWNER_ACCESS = "cross_owner_access"
    PROMPT_INJECTION = "prompt_injection"
    RETRIEVED_INSTRUCTION_INJECTION = "retrieved_instruction_injection"
    DATA_EXFILTRATION = "data_exfiltration"
    SECRET_EXPOSURE = "secret_exposure"
    RAW_FINANCIAL_EMBEDDING = "raw_financial_embedding"
    UNGROUNDED_FINANCIAL_CLAIM = "ungrounded_financial_claim"
    PROHIBITED_FINANCIAL_ACTION = "prohibited_financial_action"
    UNSAFE_FINANCIAL_ADVICE = "unsafe_financial_advice"
    RAW_PROMPT_LOGGING = "raw_prompt_logging"
    CHAIN_OF_THOUGHT_EXPOSURE = "chain_of_thought_exposure"
