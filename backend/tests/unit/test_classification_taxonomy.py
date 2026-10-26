"""Tests for the closed Phase 7 transaction taxonomy."""

import pytest

from falcon_api.classification.taxonomy import (
    CATEGORY_DEFINITIONS,
    CLASSIFICATION_TAXONOMY_VERSION,
    ClassificationCategoryCode,
    ClassificationSubcategoryCode,
    category_definition,
    subcategory_definition,
    validate_classification_target,
)
from falcon_api.models.enums import TransactionType


def test_taxonomy_has_one_definition_for_every_stable_code() -> None:
    categories = [definition.code for definition in CATEGORY_DEFINITIONS]
    subcategories = [
        subcategory.code
        for definition in CATEGORY_DEFINITIONS
        for subcategory in definition.subcategories
    ]

    assert set(categories) == set(ClassificationCategoryCode)
    assert len(categories) == len(set(categories))
    assert set(subcategories) == set(ClassificationSubcategoryCode)
    assert len(subcategories) == len(set(subcategories))
    assert CLASSIFICATION_TAXONOMY_VERSION == "2026.1"


def test_taxonomy_definitions_are_displayable_and_non_empty() -> None:
    for definition in CATEGORY_DEFINITIONS:
        assert definition.display_name.strip()
        assert definition.subcategories
        for subcategory in definition.subcategories:
            assert subcategory.display_name.strip()
            assert subcategory.transaction_types


def test_reviewed_food_income_and_transfer_hierarchy_is_stable() -> None:
    food = category_definition(ClassificationCategoryCode.FOOD_DINING)
    income = category_definition(ClassificationCategoryCode.INCOME)
    transfer = category_definition(ClassificationCategoryCode.TRANSFER)

    assert {item.code for item in food.subcategories} == {
        ClassificationSubcategoryCode.GROCERIES,
        ClassificationSubcategoryCode.RESTAURANTS,
        ClassificationSubcategoryCode.FOOD_DELIVERY,
    }
    assert ClassificationSubcategoryCode.SALARY in {
        item.code for item in income.subcategories
    }
    assert {item.code for item in transfer.subcategories} == {
        ClassificationSubcategoryCode.SELF_TRANSFER,
        ClassificationSubcategoryCode.PERSON_TRANSFER,
    }


def test_subcategory_lookup_returns_its_single_parent() -> None:
    parent, definition = subcategory_definition(
        ClassificationSubcategoryCode.MUTUAL_FUND
    )

    assert parent is ClassificationCategoryCode.INVESTMENT
    assert definition.display_name == "Mutual Fund"


def test_target_validation_rejects_wrong_parent() -> None:
    with pytest.raises(ValueError, match="does not belong"):
        validate_classification_target(
            category=ClassificationCategoryCode.SHOPPING,
            subcategory=ClassificationSubcategoryCode.SALARY,
        )


def test_target_validation_rejects_incompatible_transaction_type() -> None:
    with pytest.raises(ValueError, match="incompatible"):
        validate_classification_target(
            category=ClassificationCategoryCode.INCOME,
            subcategory=ClassificationSubcategoryCode.SALARY,
            transaction_type=TransactionType.EXPENSE,
        )


@pytest.mark.parametrize(
    "transaction_type",
    [TransactionType.EXPENSE, TransactionType.TRANSFER],
)
def test_cash_withdrawal_accepts_import_and_transfer_representations(
    transaction_type: TransactionType,
) -> None:
    validate_classification_target(
        category=ClassificationCategoryCode.CASH,
        subcategory=ClassificationSubcategoryCode.ATM_WITHDRAWAL,
        transaction_type=transaction_type,
    )
