"""Versioned high-precision transaction classification rules."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from falcon_api.classification.features import ClassificationFeatures, PaymentChannel
from falcon_api.classification.merchant_knowledge import (
    DEFAULT_MERCHANT_KNOWLEDGE_BASE,
    MerchantKnowledgeBase,
)
from falcon_api.classification.taxonomy import (
    ClassificationCategoryCode,
    ClassificationSubcategoryCode,
    validate_classification_target,
)
from falcon_api.classification.types import ClassificationReasonCode
from falcon_api.models.enums import TransactionType


CLASSIFICATION_RULESET_VERSION = "2026.1"
MERCHANT_RULE_PRIORITY = 1000
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_VERSION_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_TOKEN = re.compile(r"^[a-z0-9_]+$")


class RuleMatchKind(StrEnum):
    """Internal reviewed evidence type without raw source content."""

    MERCHANT = "merchant"
    KEYWORD = "keyword"


@dataclass(frozen=True, slots=True)
class RuleMatch:
    """One bounded rule candidate safe for orchestration and audit."""

    rule_id: str
    kind: RuleMatchKind
    category: ClassificationCategoryCode
    subcategory: ClassificationSubcategoryCode
    confidence: Decimal
    reason_code: ClassificationReasonCode
    priority: int
    ruleset_version: str = CLASSIFICATION_RULESET_VERSION
    merchant_knowledge_version: str | None = None


@dataclass(frozen=True, slots=True)
class RuleEvaluation:
    """Deterministically selected rule result or an explicit conflict."""

    selected: RuleMatch | None
    matches: tuple[RuleMatch, ...]
    conflicted: bool
    ruleset_version: str = CLASSIFICATION_RULESET_VERSION
    merchant_knowledge_version: str | None = None


@dataclass(frozen=True, slots=True)
class KeywordRule:
    """One exact-token rule over the shared feature representation."""

    rule_id: str
    category: ClassificationCategoryCode
    subcategory: ClassificationSubcategoryCode
    transaction_types: frozenset[TransactionType]
    required_any: frozenset[str] = frozenset()
    required_all: frozenset[str] = frozenset()
    excluded: frozenset[str] = frozenset()
    payment_channels: frozenset[PaymentChannel] = frozenset()
    priority: int = 500
    confidence: Decimal = Decimal("0.98")

    def __post_init__(self) -> None:
        if _IDENTIFIER.fullmatch(self.rule_id) is None:
            raise ValueError("rule_id must be a stable identifier.")
        if not self.transaction_types:
            raise ValueError("A keyword rule requires transaction types.")
        if not (self.required_any or self.required_all or self.payment_channels):
            if self.transaction_types != frozenset({TransactionType.TRANSFER}):
                raise ValueError("A keyword rule requires bounded evidence.")
        token_sets = (self.required_any, self.required_all, self.excluded)
        if any(
            _TOKEN.fullmatch(token) is None
            for values in token_sets
            for token in values
        ):
            raise ValueError("Rule tokens must be normalized single tokens.")
        if (self.required_any | self.required_all) & self.excluded:
            raise ValueError("Required and excluded rule tokens cannot overlap.")
        if not 0 <= self.priority <= MERCHANT_RULE_PRIORITY:
            raise ValueError("priority is outside the reviewed range.")
        if (
            not isinstance(self.confidence, Decimal)
            or not self.confidence.is_finite()
            or not Decimal("0") < self.confidence <= Decimal("1")
        ):
            raise ValueError("confidence must be an exact decimal in (0, 1].")
        for transaction_type in self.transaction_types:
            validate_classification_target(
                category=self.category,
                subcategory=self.subcategory,
                transaction_type=transaction_type,
            )

    def matches(self, features: ClassificationFeatures) -> bool:
        """Return whether all reviewed predicates match the shared features."""
        if features.transaction_type not in self.transaction_types:
            return False
        if (
            self.payment_channels
            and features.payment_channel not in self.payment_channels
        ):
            return False
        tokens = frozenset(features.description_tokens)
        if self.required_all and not self.required_all.issubset(tokens):
            return False
        if self.required_any and not self.required_any.intersection(tokens):
            return False
        return not self.excluded.intersection(tokens)

    def to_match(
        self,
        *,
        ruleset_version: str = CLASSIFICATION_RULESET_VERSION,
    ) -> RuleMatch:
        """Return bounded provenance for a successful match."""
        return RuleMatch(
            rule_id=self.rule_id,
            kind=RuleMatchKind.KEYWORD,
            category=self.category,
            subcategory=self.subcategory,
            confidence=self.confidence,
            reason_code=ClassificationReasonCode.KEYWORD_RULE,
            priority=self.priority,
            ruleset_version=ruleset_version,
        )


DEFAULT_KEYWORD_RULES = (
    KeywordRule(
        "internal_transfer",
        ClassificationCategoryCode.TRANSFER,
        ClassificationSubcategoryCode.SELF_TRANSFER,
        frozenset({TransactionType.TRANSFER}),
        priority=950,
        confidence=Decimal("1"),
    ),
    KeywordRule(
        "atm_withdrawal",
        ClassificationCategoryCode.CASH,
        ClassificationSubcategoryCode.ATM_WITHDRAWAL,
        frozenset({TransactionType.EXPENSE, TransactionType.TRANSFER}),
        payment_channels=frozenset({PaymentChannel.ATM}),
        priority=900,
        confidence=Decimal("0.99"),
    ),
    KeywordRule(
        "cash_deposit",
        ClassificationCategoryCode.CASH,
        ClassificationSubcategoryCode.CASH_DEPOSIT,
        frozenset({TransactionType.INCOME, TransactionType.TRANSFER}),
        required_all=frozenset({"cash", "deposit"}),
        priority=900,
        confidence=Decimal("0.99"),
    ),
    KeywordRule(
        "salary_income",
        ClassificationCategoryCode.INCOME,
        ClassificationSubcategoryCode.SALARY,
        frozenset({TransactionType.INCOME}),
        required_any=frozenset({"salary", "payroll"}),
        priority=850,
        confidence=Decimal("0.99"),
    ),
    KeywordRule(
        "cashback_income",
        ClassificationCategoryCode.INCOME,
        ClassificationSubcategoryCode.CASHBACK,
        frozenset({TransactionType.INCOME}),
        required_any=frozenset({"cashback"}),
        priority=840,
        confidence=Decimal("0.99"),
    ),
    KeywordRule(
        "refund_income",
        ClassificationCategoryCode.INCOME,
        ClassificationSubcategoryCode.REFUND,
        frozenset({TransactionType.INCOME}),
        required_any=frozenset({"refund", "reversal"}),
        priority=830,
        confidence=Decimal("0.98"),
    ),
    KeywordRule(
        "interest_income",
        ClassificationCategoryCode.INCOME,
        ClassificationSubcategoryCode.INTEREST,
        frozenset({TransactionType.INCOME}),
        required_any=frozenset({"interest"}),
        priority=820,
        confidence=Decimal("0.98"),
    ),
    KeywordRule(
        "emi_payment",
        ClassificationCategoryCode.FINANCIAL,
        ClassificationSubcategoryCode.EMI_LOAN_PAYMENT,
        frozenset({TransactionType.EXPENSE}),
        required_any=frozenset({"emi", "loanrepayment"}),
        priority=820,
        confidence=Decimal("0.98"),
    ),
    KeywordRule(
        "rent_payment",
        ClassificationCategoryCode.HOUSING,
        ClassificationSubcategoryCode.RENT,
        frozenset({TransactionType.EXPENSE}),
        required_any=frozenset({"rent"}),
        priority=810,
        confidence=Decimal("0.98"),
    ),
    KeywordRule(
        "sip_investment",
        ClassificationCategoryCode.INVESTMENT,
        ClassificationSubcategoryCode.MUTUAL_FUND,
        frozenset({TransactionType.EXPENSE}),
        required_any=frozenset({"sip"}),
        priority=810,
        confidence=Decimal("0.98"),
    ),
    KeywordRule(
        "bank_charge",
        ClassificationCategoryCode.FINANCIAL,
        ClassificationSubcategoryCode.BANK_CHARGES,
        frozenset({TransactionType.EXPENSE}),
        required_any=frozenset({"charge", "charges", "bankcharge"}),
        priority=800,
        confidence=Decimal("0.97"),
    ),
    KeywordRule(
        "fuel_purchase",
        ClassificationCategoryCode.TRANSPORTATION,
        ClassificationSubcategoryCode.FUEL,
        frozenset({TransactionType.EXPENSE}),
        required_any=frozenset({"petrol", "diesel", "fuel"}),
        priority=780,
        confidence=Decimal("0.96"),
    ),
    KeywordRule(
        "electricity_utility",
        ClassificationCategoryCode.HOUSING,
        ClassificationSubcategoryCode.UTILITIES,
        frozenset({TransactionType.EXPENSE}),
        required_any=frozenset({"electricity", "bescom", "powerbill"}),
        priority=760,
        confidence=Decimal("0.96"),
    ),
)


class ClassificationRulesEngine:
    """Evaluate reviewed merchant and keyword rules deterministically."""

    def __init__(
        self,
        *,
        merchant_knowledge: MerchantKnowledgeBase = DEFAULT_MERCHANT_KNOWLEDGE_BASE,
        keyword_rules: tuple[KeywordRule, ...] = DEFAULT_KEYWORD_RULES,
        ruleset_version: str = CLASSIFICATION_RULESET_VERSION,
    ) -> None:
        if _VERSION_IDENTIFIER.fullmatch(ruleset_version) is None:
            raise ValueError("ruleset_version must be a stable identifier.")
        identifiers = [rule.rule_id for rule in keyword_rules]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Keyword rule identifiers must be unique.")
        self._merchant_knowledge = merchant_knowledge
        self._keyword_rules = keyword_rules
        self.ruleset_version = ruleset_version

    def evaluate(self, features: ClassificationFeatures) -> RuleEvaluation:
        """Return the highest-priority unambiguous candidate and all matches."""
        matches: list[RuleMatch] = []
        merchant = self._merchant_knowledge.resolve(features.normalized_merchant)
        if (
            merchant is not None
            and features.transaction_type in merchant.transaction_types
        ):
            matches.append(
                RuleMatch(
                    rule_id=f"merchant.{merchant.merchant_id}",
                    kind=RuleMatchKind.MERCHANT,
                    category=merchant.category,
                    subcategory=merchant.subcategory,
                    confidence=merchant.confidence,
                    reason_code=ClassificationReasonCode.KNOWN_MERCHANT,
                    priority=MERCHANT_RULE_PRIORITY,
                    ruleset_version=self.ruleset_version,
                    merchant_knowledge_version=self._merchant_knowledge.version,
                )
            )
        matches.extend(
            rule.to_match(ruleset_version=self.ruleset_version)
            for rule in self._keyword_rules
            if rule.matches(features)
        )
        ordered = tuple(
            sorted(
                matches,
                key=lambda match: (
                    -match.priority,
                    -match.confidence,
                    match.rule_id,
                ),
            )
        )
        if not ordered:
            return RuleEvaluation(
                selected=None,
                matches=(),
                conflicted=False,
                ruleset_version=self.ruleset_version,
                merchant_knowledge_version=self._merchant_knowledge.version,
            )
        top_priority = ordered[0].priority
        leading = tuple(match for match in ordered if match.priority == top_priority)
        targets = {(match.category, match.subcategory) for match in leading}
        conflicted = len(targets) > 1
        return RuleEvaluation(
            selected=None if conflicted else leading[0],
            matches=ordered,
            conflicted=conflicted,
            ruleset_version=self.ruleset_version,
            merchant_knowledge_version=self._merchant_knowledge.version,
        )
