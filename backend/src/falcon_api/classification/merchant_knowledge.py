"""Versioned, reviewed exact-match merchant knowledge for classification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from falcon_api.classification.features import normalize_merchant
from falcon_api.classification.taxonomy import (
    ClassificationCategoryCode,
    ClassificationSubcategoryCode,
    validate_classification_target,
)
from falcon_api.models.enums import TransactionType


MERCHANT_KNOWLEDGE_VERSION = "2026.1"
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_VERSION_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")


@dataclass(frozen=True, slots=True)
class MerchantDefinition:
    """One reviewed merchant and its exact normalized aliases."""

    merchant_id: str
    display_name: str
    aliases: tuple[str, ...]
    category: ClassificationCategoryCode
    subcategory: ClassificationSubcategoryCode
    transaction_types: frozenset[TransactionType]
    confidence: Decimal = Decimal("0.99")

    def __post_init__(self) -> None:
        if _IDENTIFIER.fullmatch(self.merchant_id) is None:
            raise ValueError("merchant_id must be a stable identifier.")
        if not self.display_name.strip() or len(self.display_name) > 100:
            raise ValueError("display_name must be bounded and non-blank.")
        if not self.aliases:
            raise ValueError("A merchant requires at least one reviewed alias.")
        normalized_aliases = tuple(normalize_merchant(alias) for alias in self.aliases)
        if any(alias is None for alias in normalized_aliases):
            raise ValueError("Merchant aliases must normalize to non-blank values.")
        if len(set(normalized_aliases)) != len(normalized_aliases):
            raise ValueError("Merchant aliases must be unique after normalization.")
        if not self.transaction_types:
            raise ValueError("A merchant requires compatible transaction types.")
        for transaction_type in self.transaction_types:
            validate_classification_target(
                category=self.category,
                subcategory=self.subcategory,
                transaction_type=transaction_type,
            )
        if (
            not isinstance(self.confidence, Decimal)
            or not self.confidence.is_finite()
            or not Decimal("0") < self.confidence <= Decimal("1")
        ):
            raise ValueError("confidence must be an exact decimal in (0, 1].")


class MerchantKnowledgeBase:
    """Resolve reviewed aliases exactly without fuzzy or prefix matching."""

    def __init__(
        self,
        definitions: tuple[MerchantDefinition, ...],
        *,
        version: str = MERCHANT_KNOWLEDGE_VERSION,
    ) -> None:
        if _VERSION_IDENTIFIER.fullmatch(version) is None:
            raise ValueError("version must be a stable identifier.")
        if not definitions:
            raise ValueError("A merchant knowledge base cannot be empty.")
        identifiers: set[str] = set()
        aliases: dict[str, MerchantDefinition] = {}
        for definition in definitions:
            if definition.merchant_id in identifiers:
                raise ValueError("Merchant identifiers must be unique.")
            identifiers.add(definition.merchant_id)
            for raw_alias in definition.aliases:
                alias = normalize_merchant(raw_alias)
                if alias in aliases:
                    raise ValueError("Merchant aliases cannot map ambiguously.")
                aliases[alias] = definition
        self._definitions = definitions
        self._aliases = aliases
        self.version = version

    @property
    def definitions(self) -> tuple[MerchantDefinition, ...]:
        """Return the immutable reviewed merchant definitions."""
        return self._definitions

    def resolve(self, merchant: str | None) -> MerchantDefinition | None:
        """Return an exact normalized alias match, never a fuzzy guess."""
        normalized = normalize_merchant(merchant)
        if normalized is None:
            return None
        return self._aliases.get(normalized)


def _expense_merchant(
    merchant_id: str,
    display_name: str,
    aliases: tuple[str, ...],
    category: ClassificationCategoryCode,
    subcategory: ClassificationSubcategoryCode,
) -> MerchantDefinition:
    return MerchantDefinition(
        merchant_id=merchant_id,
        display_name=display_name,
        aliases=aliases,
        category=category,
        subcategory=subcategory,
        transaction_types=frozenset({TransactionType.EXPENSE}),
    )


DEFAULT_MERCHANT_DEFINITIONS = (
    _expense_merchant(
        "swiggy",
        "Swiggy",
        ("Swiggy", "Swiggy Limited"),
        ClassificationCategoryCode.FOOD_DINING,
        ClassificationSubcategoryCode.FOOD_DELIVERY,
    ),
    _expense_merchant(
        "zomato",
        "Zomato",
        ("Zomato", "Zomato Limited"),
        ClassificationCategoryCode.FOOD_DINING,
        ClassificationSubcategoryCode.FOOD_DELIVERY,
    ),
    _expense_merchant(
        "swiggy_instamart",
        "Swiggy Instamart",
        ("Swiggy Instamart", "Instamart"),
        ClassificationCategoryCode.FOOD_DINING,
        ClassificationSubcategoryCode.GROCERIES,
    ),
    _expense_merchant(
        "bigbasket",
        "BigBasket",
        ("BigBasket", "Big Basket"),
        ClassificationCategoryCode.FOOD_DINING,
        ClassificationSubcategoryCode.GROCERIES,
    ),
    _expense_merchant(
        "zepto",
        "Zepto",
        ("Zepto", "Kiranakart Technologies"),
        ClassificationCategoryCode.FOOD_DINING,
        ClassificationSubcategoryCode.GROCERIES,
    ),
    _expense_merchant(
        "uber",
        "Uber",
        ("Uber",),
        ClassificationCategoryCode.TRANSPORTATION,
        ClassificationSubcategoryCode.TAXI_RIDE_SHARE,
    ),
    _expense_merchant(
        "ola",
        "Ola",
        ("Ola", "Ola Cabs", "ANI Technologies"),
        ClassificationCategoryCode.TRANSPORTATION,
        ClassificationSubcategoryCode.TAXI_RIDE_SHARE,
    ),
    _expense_merchant(
        "rapido",
        "Rapido",
        ("Rapido", "Roppen Transportation"),
        ClassificationCategoryCode.TRANSPORTATION,
        ClassificationSubcategoryCode.TAXI_RIDE_SHARE,
    ),
    _expense_merchant(
        "indian_oil",
        "Indian Oil",
        ("Indian Oil", "IOCL"),
        ClassificationCategoryCode.TRANSPORTATION,
        ClassificationSubcategoryCode.FUEL,
    ),
    _expense_merchant(
        "hpcl",
        "Hindustan Petroleum",
        ("Hindustan Petroleum", "HPCL", "HP Pay"),
        ClassificationCategoryCode.TRANSPORTATION,
        ClassificationSubcategoryCode.FUEL,
    ),
    _expense_merchant(
        "bpcl",
        "Bharat Petroleum",
        ("Bharat Petroleum", "BPCL"),
        ClassificationCategoryCode.TRANSPORTATION,
        ClassificationSubcategoryCode.FUEL,
    ),
    _expense_merchant(
        "myntra",
        "Myntra",
        ("Myntra", "Myntra Designs"),
        ClassificationCategoryCode.SHOPPING,
        ClassificationSubcategoryCode.CLOTHING,
    ),
    _expense_merchant(
        "croma",
        "Croma",
        ("Croma", "Infiniti Retail"),
        ClassificationCategoryCode.SHOPPING,
        ClassificationSubcategoryCode.ELECTRONICS,
    ),
    _expense_merchant(
        "pharmeasy",
        "PharmEasy",
        ("PharmEasy", "API Holdings"),
        ClassificationCategoryCode.HEALTHCARE,
        ClassificationSubcategoryCode.PHARMACY,
    ),
    _expense_merchant(
        "netmeds",
        "Netmeds",
        ("Netmeds", "Netmeds Marketplace"),
        ClassificationCategoryCode.HEALTHCARE,
        ClassificationSubcategoryCode.PHARMACY,
    ),
    _expense_merchant(
        "apollo_pharmacy",
        "Apollo Pharmacy",
        ("Apollo Pharmacy", "Apollo Pharmacies"),
        ClassificationCategoryCode.HEALTHCARE,
        ClassificationSubcategoryCode.PHARMACY,
    ),
    _expense_merchant(
        "netflix",
        "Netflix",
        ("Netflix", "Netflix.com"),
        ClassificationCategoryCode.ENTERTAINMENT,
        ClassificationSubcategoryCode.STREAMING,
    ),
    _expense_merchant(
        "hotstar",
        "Disney+ Hotstar",
        ("Disney+ Hotstar", "Hotstar"),
        ClassificationCategoryCode.ENTERTAINMENT,
        ClassificationSubcategoryCode.STREAMING,
    ),
    _expense_merchant(
        "spotify",
        "Spotify",
        ("Spotify", "Spotify AB"),
        ClassificationCategoryCode.ENTERTAINMENT,
        ClassificationSubcategoryCode.STREAMING,
    ),
    _expense_merchant(
        "bookmyshow",
        "BookMyShow",
        ("BookMyShow", "Bigtree Entertainment"),
        ClassificationCategoryCode.ENTERTAINMENT,
        ClassificationSubcategoryCode.MOVIES_EVENTS,
    ),
    _expense_merchant(
        "coursera",
        "Coursera",
        ("Coursera", "Coursera Inc"),
        ClassificationCategoryCode.EDUCATION,
        ClassificationSubcategoryCode.COURSES,
    ),
    _expense_merchant(
        "udemy",
        "Udemy",
        ("Udemy", "Udemy.com"),
        ClassificationCategoryCode.EDUCATION,
        ClassificationSubcategoryCode.COURSES,
    ),
    _expense_merchant(
        "zerodha",
        "Zerodha",
        ("Zerodha", "Zerodha Broking"),
        ClassificationCategoryCode.INVESTMENT,
        ClassificationSubcategoryCode.STOCKS,
    ),
    _expense_merchant(
        "bescom",
        "BESCOM",
        ("BESCOM", "Bangalore Electricity Supply Company"),
        ClassificationCategoryCode.HOUSING,
        ClassificationSubcategoryCode.UTILITIES,
    ),
)

DEFAULT_MERCHANT_KNOWLEDGE_BASE = MerchantKnowledgeBase(
    DEFAULT_MERCHANT_DEFINITIONS
)
