"""Tests for the reviewed Phase 7 merchant knowledge base."""

from decimal import Decimal

import pytest
from falcon_api.classification.merchant_knowledge import (
    DEFAULT_MERCHANT_DEFINITIONS,
    DEFAULT_MERCHANT_KNOWLEDGE_BASE,
    MERCHANT_KNOWLEDGE_VERSION,
    MerchantDefinition,
    MerchantKnowledgeBase,
)
from falcon_api.classification.features import normalize_merchant
from falcon_api.classification.taxonomy import (
    ClassificationCategoryCode,
    ClassificationSubcategoryCode,
    validate_classification_target,
)
from falcon_api.models.enums import TransactionType


def _merchant(
    *,
    merchant_id: str = "reviewed_merchant",
    display_name: str = "Reviewed Merchant",
    aliases: tuple[str, ...] = ("Reviewed Merchant",),
    transaction_types: frozenset[TransactionType] = frozenset(
        {TransactionType.EXPENSE}
    ),
    confidence: Decimal = Decimal("0.99"),
) -> MerchantDefinition:
    return MerchantDefinition(
        merchant_id=merchant_id,
        display_name=display_name,
        aliases=aliases,
        category=ClassificationCategoryCode.FOOD_DINING,
        subcategory=ClassificationSubcategoryCode.RESTAURANTS,
        transaction_types=transaction_types,
        confidence=confidence,
    )


def test_default_merchant_knowledge_is_versioned_unique_and_compatible() -> None:
    identifiers = [merchant.merchant_id for merchant in DEFAULT_MERCHANT_DEFINITIONS]
    normalized_aliases: set[str] = set()

    assert MERCHANT_KNOWLEDGE_VERSION == "2026.1"
    assert DEFAULT_MERCHANT_KNOWLEDGE_BASE.version == "2026.1"
    assert len(DEFAULT_MERCHANT_DEFINITIONS) == 24
    assert len(identifiers) == len(set(identifiers))
    for merchant in DEFAULT_MERCHANT_DEFINITIONS:
        assert merchant.display_name.strip()
        assert merchant.aliases
        for transaction_type in merchant.transaction_types:
            validate_classification_target(
                category=merchant.category,
                subcategory=merchant.subcategory,
                transaction_type=transaction_type,
            )
        for alias in merchant.aliases:
            normalized = normalize_merchant(alias)
            assert normalized is not None
            assert normalized not in normalized_aliases
            normalized_aliases.add(normalized)


@pytest.mark.parametrize(
    ("alias", "merchant_id", "subcategory"),
    [
        (" SWIGGY LIMITED ", "swiggy", ClassificationSubcategoryCode.FOOD_DELIVERY),
        ("Big Basket", "bigbasket", ClassificationSubcategoryCode.GROCERIES),
        ("ANI Technologies", "ola", ClassificationSubcategoryCode.TAXI_RIDE_SHARE),
        ("IOCL", "indian_oil", ClassificationSubcategoryCode.FUEL),
        (
            "Apollo Pharmacies",
            "apollo_pharmacy",
            ClassificationSubcategoryCode.PHARMACY,
        ),
        ("Disney+ Hotstar", "hotstar", ClassificationSubcategoryCode.STREAMING),
        ("Zerodha Broking", "zerodha", ClassificationSubcategoryCode.STOCKS),
        ("BESCOM", "bescom", ClassificationSubcategoryCode.UTILITIES),
    ],
)
def test_exact_reviewed_aliases_resolve(
    alias: str,
    merchant_id: str,
    subcategory: ClassificationSubcategoryCode,
) -> None:
    result = DEFAULT_MERCHANT_KNOWLEDGE_BASE.resolve(alias)

    assert result is not None
    assert result.merchant_id == merchant_id
    assert result.subcategory is subcategory


def test_resolution_is_exact_and_never_fuzzy_or_prefix_based() -> None:
    assert DEFAULT_MERCHANT_KNOWLEDGE_BASE.resolve("Swiggy") is not None
    assert DEFAULT_MERCHANT_KNOWLEDGE_BASE.resolve("Swiggy Bengaluru") is None
    assert DEFAULT_MERCHANT_KNOWLEDGE_BASE.resolve("Swigy") is None
    assert DEFAULT_MERCHANT_KNOWLEDGE_BASE.resolve(None) is None
    assert DEFAULT_MERCHANT_KNOWLEDGE_BASE.resolve(" ") is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"merchant_id": "Invalid ID"},
        {"display_name": " "},
        {"display_name": "x" * 101},
        {"aliases": ()},
        {"aliases": (" ",)},
        {"aliases": ("Uber", "Uber India")},
        {"transaction_types": frozenset()},
        {"confidence": Decimal("0")},
        {"confidence": Decimal("NaN")},
    ],
)
def test_merchant_definition_rejects_invalid_contracts(
    overrides: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "merchant_id": "reviewed_merchant",
        "display_name": "Reviewed Merchant",
        "aliases": ("Reviewed Merchant",),
        "transaction_types": frozenset({TransactionType.EXPENSE}),
        "confidence": Decimal("0.99"),
    }
    values.update(overrides)

    with pytest.raises(ValueError):
        _merchant(**values)  # type: ignore[arg-type]


def test_merchant_definition_rejects_incompatible_target_type() -> None:
    with pytest.raises(ValueError, match="incompatible"):
        _merchant(transaction_types=frozenset({TransactionType.INCOME}))


def test_knowledge_base_rejects_empty_duplicate_and_ambiguous_data() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        MerchantKnowledgeBase(())
    with pytest.raises(ValueError, match="identifiers"):
        MerchantKnowledgeBase((_merchant(), _merchant()))
    with pytest.raises(ValueError, match="ambiguously"):
        MerchantKnowledgeBase(
            (
                _merchant(merchant_id="first"),
                _merchant(merchant_id="second"),
            )
        )
    with pytest.raises(ValueError, match="version"):
        MerchantKnowledgeBase((_merchant(),), version="bad version")


def test_knowledge_definitions_are_exposed_as_an_immutable_tuple() -> None:
    knowledge = MerchantKnowledgeBase((_merchant(),), version="test.1")

    assert knowledge.definitions == (_merchant(),)
