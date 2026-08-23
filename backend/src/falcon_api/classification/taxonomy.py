"""Versioned first-release transaction classification taxonomy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from falcon_api.models.enums import CategoryKind, TransactionType


CLASSIFICATION_TAXONOMY_VERSION = "2026.1"


class ClassificationCategoryCode(StrEnum):
    """Stable top-level meanings predicted by the classifier."""

    FOOD_DINING = "food_dining"
    HOUSING = "housing"
    TRANSPORTATION = "transportation"
    SHOPPING = "shopping"
    HEALTHCARE = "healthcare"
    EDUCATION = "education"
    ENTERTAINMENT = "entertainment"
    FINANCIAL = "financial"
    INCOME = "income"
    TRANSFER = "transfer"
    INVESTMENT = "investment"
    CASH = "cash"
    OTHER = "other"


class ClassificationSubcategoryCode(StrEnum):
    """Stable leaf meanings within the first-release taxonomy."""

    GROCERIES = "groceries"
    RESTAURANTS = "restaurants"
    FOOD_DELIVERY = "food_delivery"
    RENT = "rent"
    HOME_MAINTENANCE = "home_maintenance"
    UTILITIES = "utilities"
    FUEL = "fuel"
    PUBLIC_TRANSPORT = "public_transport"
    TAXI_RIDE_SHARE = "taxi_ride_share"
    VEHICLE_MAINTENANCE = "vehicle_maintenance"
    TOLL_PARKING = "toll_parking"
    CLOTHING = "clothing"
    ELECTRONICS = "electronics"
    HOUSEHOLD_GOODS = "household_goods"
    GENERAL_SHOPPING = "general_shopping"
    PHARMACY = "pharmacy"
    HOSPITAL_CLINIC = "hospital_clinic"
    HEALTH_INSURANCE = "health_insurance"
    TUITION_FEES = "tuition_fees"
    COURSES = "courses"
    BOOKS_SUPPLIES = "books_supplies"
    STREAMING = "streaming"
    MOVIES_EVENTS = "movies_events"
    GAMING = "gaming"
    HOBBIES = "hobbies"
    EMI_LOAN_PAYMENT = "emi_loan_payment"
    BANK_CHARGES = "bank_charges"
    TAXES = "taxes"
    OTHER_INSURANCE = "other_insurance"
    SALARY = "salary"
    FREELANCE = "freelance"
    BUSINESS_INCOME = "business_income"
    INTEREST = "interest"
    DIVIDEND = "dividend"
    REFUND = "refund"
    CASHBACK = "cashback"
    OTHER_INCOME = "other_income"
    SELF_TRANSFER = "self_transfer"
    PERSON_TRANSFER = "person_transfer"
    MUTUAL_FUND = "mutual_fund"
    STOCKS = "stocks"
    FIXED_DEPOSIT = "fixed_deposit"
    RETIREMENT = "retirement"
    OTHER_INVESTMENT = "other_investment"
    ATM_WITHDRAWAL = "atm_withdrawal"
    CASH_DEPOSIT = "cash_deposit"
    UNCATEGORIZED = "uncategorized"
    OTHER_EXPENSE = "other_expense"


@dataclass(frozen=True, slots=True)
class SubcategoryDefinition:
    """One displayable leaf belonging to exactly one category."""

    code: ClassificationSubcategoryCode
    display_name: str
    kind: CategoryKind
    transaction_types: frozenset[TransactionType]


@dataclass(frozen=True, slots=True)
class CategoryDefinition:
    """One top-level category containing reviewed classification leaves."""

    code: ClassificationCategoryCode
    display_name: str
    subcategories: tuple[SubcategoryDefinition, ...]


def _subcategories(
    kind: CategoryKind,
    *items: tuple[ClassificationSubcategoryCode, str],
) -> tuple[SubcategoryDefinition, ...]:
    transaction_type = {
        CategoryKind.INCOME: TransactionType.INCOME,
        CategoryKind.EXPENSE: TransactionType.EXPENSE,
        CategoryKind.TRANSFER: TransactionType.TRANSFER,
    }[kind]
    return tuple(
        SubcategoryDefinition(
            code=code,
            display_name=display_name,
            kind=kind,
            transaction_types=frozenset({transaction_type}),
        )
        for code, display_name in items
    )


CATEGORY_DEFINITIONS = (
    CategoryDefinition(
        ClassificationCategoryCode.FOOD_DINING,
        "Food & Dining",
        _subcategories(
            CategoryKind.EXPENSE,
            (ClassificationSubcategoryCode.GROCERIES, "Groceries"),
            (ClassificationSubcategoryCode.RESTAURANTS, "Restaurants"),
            (ClassificationSubcategoryCode.FOOD_DELIVERY, "Food Delivery"),
        ),
    ),
    CategoryDefinition(
        ClassificationCategoryCode.HOUSING,
        "Housing",
        _subcategories(
            CategoryKind.EXPENSE,
            (ClassificationSubcategoryCode.RENT, "Rent"),
            (ClassificationSubcategoryCode.HOME_MAINTENANCE, "Maintenance"),
            (ClassificationSubcategoryCode.UTILITIES, "Utilities"),
        ),
    ),
    CategoryDefinition(
        ClassificationCategoryCode.TRANSPORTATION,
        "Transportation",
        _subcategories(
            CategoryKind.EXPENSE,
            (ClassificationSubcategoryCode.FUEL, "Fuel"),
            (ClassificationSubcategoryCode.PUBLIC_TRANSPORT, "Public Transport"),
            (ClassificationSubcategoryCode.TAXI_RIDE_SHARE, "Taxi & Ride Share"),
            (
                ClassificationSubcategoryCode.VEHICLE_MAINTENANCE,
                "Vehicle Maintenance",
            ),
            (ClassificationSubcategoryCode.TOLL_PARKING, "Toll & Parking"),
        ),
    ),
    CategoryDefinition(
        ClassificationCategoryCode.SHOPPING,
        "Shopping",
        _subcategories(
            CategoryKind.EXPENSE,
            (ClassificationSubcategoryCode.CLOTHING, "Clothing"),
            (ClassificationSubcategoryCode.ELECTRONICS, "Electronics"),
            (ClassificationSubcategoryCode.HOUSEHOLD_GOODS, "Household Goods"),
            (ClassificationSubcategoryCode.GENERAL_SHOPPING, "General Shopping"),
        ),
    ),
    CategoryDefinition(
        ClassificationCategoryCode.HEALTHCARE,
        "Healthcare",
        _subcategories(
            CategoryKind.EXPENSE,
            (ClassificationSubcategoryCode.PHARMACY, "Pharmacy"),
            (ClassificationSubcategoryCode.HOSPITAL_CLINIC, "Hospital & Clinic"),
            (ClassificationSubcategoryCode.HEALTH_INSURANCE, "Health Insurance"),
        ),
    ),
    CategoryDefinition(
        ClassificationCategoryCode.EDUCATION,
        "Education",
        _subcategories(
            CategoryKind.EXPENSE,
            (ClassificationSubcategoryCode.TUITION_FEES, "Tuition & Fees"),
            (ClassificationSubcategoryCode.COURSES, "Courses"),
            (ClassificationSubcategoryCode.BOOKS_SUPPLIES, "Books & Supplies"),
        ),
    ),
    CategoryDefinition(
        ClassificationCategoryCode.ENTERTAINMENT,
        "Entertainment",
        _subcategories(
            CategoryKind.EXPENSE,
            (ClassificationSubcategoryCode.STREAMING, "Streaming"),
            (ClassificationSubcategoryCode.MOVIES_EVENTS, "Movies & Events"),
            (ClassificationSubcategoryCode.GAMING, "Gaming"),
            (ClassificationSubcategoryCode.HOBBIES, "Hobbies"),
        ),
    ),
    CategoryDefinition(
        ClassificationCategoryCode.FINANCIAL,
        "Financial",
        _subcategories(
            CategoryKind.EXPENSE,
            (ClassificationSubcategoryCode.EMI_LOAN_PAYMENT, "EMI & Loan Payment"),
            (ClassificationSubcategoryCode.BANK_CHARGES, "Bank Charges"),
            (ClassificationSubcategoryCode.TAXES, "Taxes"),
            (ClassificationSubcategoryCode.OTHER_INSURANCE, "Other Insurance"),
        ),
    ),
    CategoryDefinition(
        ClassificationCategoryCode.INCOME,
        "Income",
        _subcategories(
            CategoryKind.INCOME,
            (ClassificationSubcategoryCode.SALARY, "Salary"),
            (ClassificationSubcategoryCode.FREELANCE, "Freelance"),
            (ClassificationSubcategoryCode.BUSINESS_INCOME, "Business Income"),
            (ClassificationSubcategoryCode.INTEREST, "Interest"),
            (ClassificationSubcategoryCode.DIVIDEND, "Dividend"),
            (ClassificationSubcategoryCode.REFUND, "Refund"),
            (ClassificationSubcategoryCode.CASHBACK, "Cashback"),
            (ClassificationSubcategoryCode.OTHER_INCOME, "Other Income"),
        ),
    ),
    CategoryDefinition(
        ClassificationCategoryCode.TRANSFER,
        "Transfer",
        _subcategories(
            CategoryKind.TRANSFER,
            (ClassificationSubcategoryCode.SELF_TRANSFER, "Self Transfer"),
            (ClassificationSubcategoryCode.PERSON_TRANSFER, "Person Transfer"),
        ),
    ),
    CategoryDefinition(
        ClassificationCategoryCode.INVESTMENT,
        "Investment",
        _subcategories(
            CategoryKind.EXPENSE,
            (ClassificationSubcategoryCode.MUTUAL_FUND, "Mutual Fund"),
            (ClassificationSubcategoryCode.STOCKS, "Stocks"),
            (ClassificationSubcategoryCode.FIXED_DEPOSIT, "Fixed Deposit"),
            (ClassificationSubcategoryCode.RETIREMENT, "Retirement"),
            (ClassificationSubcategoryCode.OTHER_INVESTMENT, "Other Investment"),
        ),
    ),
    CategoryDefinition(
        ClassificationCategoryCode.CASH,
        "Cash",
        (
            SubcategoryDefinition(
                ClassificationSubcategoryCode.ATM_WITHDRAWAL,
                "ATM Withdrawal",
                CategoryKind.EXPENSE,
                frozenset({TransactionType.EXPENSE, TransactionType.TRANSFER}),
            ),
            SubcategoryDefinition(
                ClassificationSubcategoryCode.CASH_DEPOSIT,
                "Cash Deposit",
                CategoryKind.INCOME,
                frozenset({TransactionType.INCOME, TransactionType.TRANSFER}),
            ),
        ),
    ),
    CategoryDefinition(
        ClassificationCategoryCode.OTHER,
        "Other",
        _subcategories(
            CategoryKind.EXPENSE,
            (ClassificationSubcategoryCode.UNCATEGORIZED, "Uncategorized"),
            (ClassificationSubcategoryCode.OTHER_EXPENSE, "Other Expense"),
        ),
    ),
)

_CATEGORY_BY_CODE = {
    definition.code: definition for definition in CATEGORY_DEFINITIONS
}
_SUBCATEGORY_BY_CODE = {
    subcategory.code: (definition.code, subcategory)
    for definition in CATEGORY_DEFINITIONS
    for subcategory in definition.subcategories
}


def category_definition(code: ClassificationCategoryCode) -> CategoryDefinition:
    """Return one category definition from the closed taxonomy."""
    return _CATEGORY_BY_CODE[code]


def subcategory_definition(
    code: ClassificationSubcategoryCode,
) -> tuple[ClassificationCategoryCode, SubcategoryDefinition]:
    """Return the parent and definition for one taxonomy leaf."""
    return _SUBCATEGORY_BY_CODE[code]


def validate_classification_target(
    *,
    category: ClassificationCategoryCode,
    subcategory: ClassificationSubcategoryCode,
    transaction_type: TransactionType | None = None,
) -> None:
    """Reject an invalid parent/leaf or transaction/category combination."""
    parent, _ = subcategory_definition(subcategory)
    if parent != category:
        raise ValueError("The subcategory does not belong to the category.")
    if (
        transaction_type is not None
        and transaction_type
        not in subcategory_definition(subcategory)[1].transaction_types
    ):
        raise ValueError("The category is incompatible with the transaction type.")
