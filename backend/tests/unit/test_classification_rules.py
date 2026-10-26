"""Tests for deterministic Phase 7 merchant and keyword rules."""

from datetime import date
from decimal import Decimal

import pytest
from falcon_api.classification.features import (
    ClassificationFeatures,
    TransactionFeatureInput,
    build_classification_features,
)
from falcon_api.classification.rules import (
    CLASSIFICATION_RULESET_VERSION,
    DEFAULT_KEYWORD_RULES,
    ClassificationRulesEngine,
    KeywordRule,
    RuleMatchKind,
)
from falcon_api.classification.taxonomy import (
    ClassificationCategoryCode,
    ClassificationSubcategoryCode,
)
from falcon_api.classification.types import ClassificationReasonCode
from falcon_api.models.enums import TransactionType


def _features(
    description: str,
    *,
    merchant_name: str | None = None,
    transaction_type: TransactionType = TransactionType.EXPENSE,
) -> ClassificationFeatures:
    signed_amount = {
        TransactionType.INCOME: Decimal("1000"),
        TransactionType.EXPENSE: Decimal("-1000"),
        TransactionType.TRANSFER: Decimal("-1000"),
        TransactionType.ADJUSTMENT: Decimal("-1000"),
    }[transaction_type]
    return build_classification_features(
        TransactionFeatureInput(
            description=description,
            merchant_name=merchant_name,
            transaction_type=transaction_type,
            signed_amount=signed_amount,
            transaction_date=date(2026, 8, 23),
            account_currency="INR",
        )
    )


def _rule(
    rule_id: str,
    *,
    category: ClassificationCategoryCode = ClassificationCategoryCode.HOUSING,
    subcategory: ClassificationSubcategoryCode = ClassificationSubcategoryCode.RENT,
    priority: int = 500,
    required_any: frozenset[str] = frozenset({"signal"}),
    confidence: Decimal = Decimal("0.90"),
) -> KeywordRule:
    return KeywordRule(
        rule_id=rule_id,
        category=category,
        subcategory=subcategory,
        transaction_types=frozenset({TransactionType.EXPENSE}),
        required_any=required_any,
        priority=priority,
        confidence=confidence,
    )


def test_default_rule_contract_is_versioned_and_has_unique_ids() -> None:
    identifiers = [rule.rule_id for rule in DEFAULT_KEYWORD_RULES]

    assert CLASSIFICATION_RULESET_VERSION == "2026.1"
    assert len(identifiers) == len(set(identifiers))


@pytest.mark.parametrize(
    ("description", "transaction_type", "category", "subcategory"),
    [
        (
            "Internal transfer",
            TransactionType.TRANSFER,
            ClassificationCategoryCode.TRANSFER,
            ClassificationSubcategoryCode.SELF_TRANSFER,
        ),
        (
            "ATM cash withdrawal",
            TransactionType.EXPENSE,
            ClassificationCategoryCode.CASH,
            ClassificationSubcategoryCode.ATM_WITHDRAWAL,
        ),
        (
            "cash deposit",
            TransactionType.INCOME,
            ClassificationCategoryCode.CASH,
            ClassificationSubcategoryCode.CASH_DEPOSIT,
        ),
        (
            "monthly salary credit",
            TransactionType.INCOME,
            ClassificationCategoryCode.INCOME,
            ClassificationSubcategoryCode.SALARY,
        ),
        (
            "cashback received",
            TransactionType.INCOME,
            ClassificationCategoryCode.INCOME,
            ClassificationSubcategoryCode.CASHBACK,
        ),
        (
            "refund received",
            TransactionType.INCOME,
            ClassificationCategoryCode.INCOME,
            ClassificationSubcategoryCode.REFUND,
        ),
        (
            "interest credit",
            TransactionType.INCOME,
            ClassificationCategoryCode.INCOME,
            ClassificationSubcategoryCode.INTEREST,
        ),
        (
            "home loan EMI",
            TransactionType.EXPENSE,
            ClassificationCategoryCode.FINANCIAL,
            ClassificationSubcategoryCode.EMI_LOAN_PAYMENT,
        ),
        (
            "apartment rent",
            TransactionType.EXPENSE,
            ClassificationCategoryCode.HOUSING,
            ClassificationSubcategoryCode.RENT,
        ),
        (
            "monthly SIP",
            TransactionType.EXPENSE,
            ClassificationCategoryCode.INVESTMENT,
            ClassificationSubcategoryCode.MUTUAL_FUND,
        ),
        (
            "service charges",
            TransactionType.EXPENSE,
            ClassificationCategoryCode.FINANCIAL,
            ClassificationSubcategoryCode.BANK_CHARGES,
        ),
        (
            "diesel purchase",
            TransactionType.EXPENSE,
            ClassificationCategoryCode.TRANSPORTATION,
            ClassificationSubcategoryCode.FUEL,
        ),
        (
            "electricity bill",
            TransactionType.EXPENSE,
            ClassificationCategoryCode.HOUSING,
            ClassificationSubcategoryCode.UTILITIES,
        ),
    ],
)
def test_default_keyword_rules_classify_reviewed_high_precision_cases(
    description: str,
    transaction_type: TransactionType,
    category: ClassificationCategoryCode,
    subcategory: ClassificationSubcategoryCode,
) -> None:
    evaluation = ClassificationRulesEngine().evaluate(
        _features(description, transaction_type=transaction_type)
    )

    assert evaluation.selected is not None
    assert evaluation.selected.category is category
    assert evaluation.selected.subcategory is subcategory
    assert evaluation.selected.kind is RuleMatchKind.KEYWORD
    assert evaluation.selected.reason_code is ClassificationReasonCode.KEYWORD_RULE
    assert evaluation.conflicted is False


def test_known_merchant_match_has_bounded_versioned_provenance() -> None:
    evaluation = ClassificationRulesEngine().evaluate(
        _features("UPI payment", merchant_name="Swiggy")
    )

    assert evaluation.selected is not None
    assert evaluation.selected.rule_id == "merchant.swiggy"
    assert evaluation.selected.kind is RuleMatchKind.MERCHANT
    assert (
        evaluation.selected.subcategory
        is ClassificationSubcategoryCode.FOOD_DELIVERY
    )
    assert evaluation.selected.reason_code is ClassificationReasonCode.KNOWN_MERCHANT
    assert evaluation.selected.merchant_knowledge_version == "2026.1"
    assert evaluation.ruleset_version == "2026.1"
    assert "Swiggy" not in repr(evaluation.selected)


def test_inferred_electronic_merchant_flows_through_exact_knowledge() -> None:
    evaluation = ClassificationRulesEngine().evaluate(
        _features("UPI/123456789012/SWIGGY/order@okhdfcbank")
    )

    assert evaluation.selected is not None
    assert evaluation.selected.rule_id == "merchant.swiggy"
    assert evaluation.selected.kind is RuleMatchKind.MERCHANT


def test_merchant_priority_wins_over_conflicting_lower_keyword() -> None:
    evaluation = ClassificationRulesEngine().evaluate(
        _features("rent payment", merchant_name="Swiggy")
    )

    assert evaluation.selected is not None
    assert evaluation.selected.rule_id == "merchant.swiggy"
    assert len(evaluation.matches) == 2
    assert evaluation.matches[0].priority > evaluation.matches[1].priority


def test_merchant_is_not_applied_to_an_incompatible_direction() -> None:
    evaluation = ClassificationRulesEngine().evaluate(
        _features(
            "ordinary credit",
            merchant_name="Swiggy",
            transaction_type=TransactionType.INCOME,
        )
    )

    assert evaluation.selected is None
    assert evaluation.matches == ()
    assert evaluation.conflicted is False


def test_unknown_description_abstains_from_rules_without_guessing() -> None:
    evaluation = ClassificationRulesEngine().evaluate(
        _features("ordinary unrecognized purchase")
    )

    assert evaluation.selected is None
    assert evaluation.matches == ()
    assert evaluation.conflicted is False


def test_equal_priority_different_targets_produce_explicit_conflict() -> None:
    rules = (
        _rule("housing_signal"),
        _rule(
            "shopping_signal",
            category=ClassificationCategoryCode.SHOPPING,
            subcategory=ClassificationSubcategoryCode.GENERAL_SHOPPING,
        ),
    )
    evaluation = ClassificationRulesEngine(keyword_rules=rules).evaluate(
        _features("signal")
    )

    assert evaluation.selected is None
    assert evaluation.conflicted is True
    assert len(evaluation.matches) == 2


def test_equal_target_matches_select_deterministically() -> None:
    rules = (
        _rule("second", confidence=Decimal("0.91")),
        _rule("first", confidence=Decimal("0.91")),
    )
    evaluation = ClassificationRulesEngine(keyword_rules=rules).evaluate(
        _features("signal")
    )

    assert evaluation.selected is not None
    assert evaluation.selected.rule_id == "first"
    assert evaluation.conflicted is False


def test_custom_ruleset_version_propagates_to_every_result() -> None:
    engine = ClassificationRulesEngine(
        keyword_rules=(_rule("custom"),),
        ruleset_version="test.2",
    )

    evaluation = engine.evaluate(_features("signal"))

    assert evaluation.ruleset_version == "test.2"
    assert evaluation.selected is not None
    assert evaluation.selected.ruleset_version == "test.2"


def test_keyword_predicates_require_type_channel_tokens_and_exclusions() -> None:
    rule = KeywordRule(
        rule_id="bounded_predicates",
        category=ClassificationCategoryCode.HOUSING,
        subcategory=ClassificationSubcategoryCode.RENT,
        transaction_types=frozenset({TransactionType.EXPENSE}),
        required_any=frozenset({"rent", "lease"}),
        required_all=frozenset({"monthly"}),
        excluded=frozenset({"refund"}),
        payment_channels=frozenset({
            _features("UPI payment").payment_channel,
        }),
    )

    assert rule.matches(_features("UPI monthly rent")) is True
    assert rule.matches(_features("UPI monthly mortgage")) is False
    assert rule.matches(_features("monthly rent")) is False
    assert rule.matches(_features("UPI monthly rent refund")) is False
    assert (
        rule.matches(
            _features("UPI monthly rent", transaction_type=TransactionType.INCOME)
        )
        is False
    )


@pytest.mark.parametrize(
    "rule",
    [
        pytest.param(
            lambda: _rule("Invalid ID"),
            id="invalid-id",
        ),
        pytest.param(
            lambda: KeywordRule(
                "no_types",
                ClassificationCategoryCode.HOUSING,
                ClassificationSubcategoryCode.RENT,
                frozenset(),
                required_any=frozenset({"rent"}),
            ),
            id="no-types",
        ),
        pytest.param(
            lambda: KeywordRule(
                "no_evidence",
                ClassificationCategoryCode.HOUSING,
                ClassificationSubcategoryCode.RENT,
                frozenset({TransactionType.EXPENSE}),
            ),
            id="no-evidence",
        ),
        pytest.param(
            lambda: _rule("invalid_token", required_any=frozenset({"two words"})),
            id="invalid-token",
        ),
        pytest.param(
            lambda: KeywordRule(
                "overlap",
                ClassificationCategoryCode.HOUSING,
                ClassificationSubcategoryCode.RENT,
                frozenset({TransactionType.EXPENSE}),
                required_any=frozenset({"rent"}),
                excluded=frozenset({"rent"}),
            ),
            id="overlap",
        ),
        pytest.param(
            lambda: _rule("priority", priority=1001),
            id="priority",
        ),
        pytest.param(
            lambda: _rule("confidence", confidence=Decimal("0")),
            id="confidence",
        ),
    ],
)
def test_keyword_rule_rejects_invalid_contracts(rule) -> None:
    with pytest.raises(ValueError):
        rule()


def test_engine_rejects_duplicate_rule_ids_and_invalid_version() -> None:
    with pytest.raises(ValueError, match="unique"):
        ClassificationRulesEngine(
            keyword_rules=(_rule("duplicate"), _rule("duplicate"))
        )
    with pytest.raises(ValueError, match="version"):
        ClassificationRulesEngine(
            keyword_rules=(_rule("valid"),),
            ruleset_version="invalid version",
        )
