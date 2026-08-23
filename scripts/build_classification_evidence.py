"""Build the synthetic Phase 7.4 dataset and reproducible model evidence.

Inputs: no personal data; all examples are deterministic synthetic records.
Outputs: a JSONL dataset, integrity manifest, and model-comparison JSON report.
Prerequisite: install the backend with its ``ml`` extra.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from falcon_api.classification.dataset import (
    ClassificationDataset,
    DatasetSourceKind,
    LabeledFeatureSample,
    build_classification_dataset,
)
from falcon_api.classification.features import (
    TransactionFeatureInput,
    build_classification_features,
)
from falcon_api.classification.taxonomy import (
    ClassificationSubcategoryCode,
    subcategory_definition,
)
from falcon_api.classification.training import compare_classification_models
from falcon_api.models.enums import TransactionType


_SYNTHETIC_SECRET = b"falcon-phase-7.4-reproducible-synthetic-data-key"
_GROUPS_PER_LABEL = 6

_PHRASES: dict[ClassificationSubcategoryCode, tuple[str, str, str]] = {
    ClassificationSubcategoryCode.GROCERIES: (
        "weekly grocery basket",
        "supermarket food supplies",
        "fresh vegetables and provisions",
    ),
    ClassificationSubcategoryCode.RESTAURANTS: (
        "restaurant dinner",
        "cafe lunch meal",
        "dining bill",
    ),
    ClassificationSubcategoryCode.FOOD_DELIVERY: (
        "food delivery order",
        "online meal delivery",
        "takeaway order",
    ),
    ClassificationSubcategoryCode.RENT: (
        "monthly apartment rent",
        "house rent payment",
        "residential lease rent",
    ),
    ClassificationSubcategoryCode.HOME_MAINTENANCE: (
        "home plumbing repair",
        "apartment maintenance service",
        "house electrical repair",
    ),
    ClassificationSubcategoryCode.UTILITIES: (
        "monthly electricity utility",
        "water utility bill",
        "domestic power bill",
    ),
    ClassificationSubcategoryCode.FUEL: (
        "petrol fuel station",
        "diesel vehicle fuel",
        "automobile fuel purchase",
    ),
    ClassificationSubcategoryCode.PUBLIC_TRANSPORT: (
        "metro travel ticket",
        "city bus pass",
        "railway commute fare",
    ),
    ClassificationSubcategoryCode.TAXI_RIDE_SHARE: (
        "cab ride fare",
        "taxi trip",
        "ride share booking",
    ),
    ClassificationSubcategoryCode.VEHICLE_MAINTENANCE: (
        "car service repair",
        "vehicle maintenance workshop",
        "two wheeler service",
    ),
    ClassificationSubcategoryCode.TOLL_PARKING: (
        "highway toll charge",
        "vehicle parking fee",
        "fastag toll plaza",
    ),
    ClassificationSubcategoryCode.CLOTHING: (
        "clothing store purchase",
        "apparel and footwear",
        "garment shopping",
    ),
    ClassificationSubcategoryCode.ELECTRONICS: (
        "consumer electronics purchase",
        "mobile accessory store",
        "computer equipment",
    ),
    ClassificationSubcategoryCode.HOUSEHOLD_GOODS: (
        "household furnishing",
        "kitchen supplies purchase",
        "home goods store",
    ),
    ClassificationSubcategoryCode.GENERAL_SHOPPING: (
        "general retail purchase",
        "department store shopping",
        "online marketplace order",
    ),
    ClassificationSubcategoryCode.PHARMACY: (
        "pharmacy medicines",
        "prescription medicine purchase",
        "medical store bill",
    ),
    ClassificationSubcategoryCode.HOSPITAL_CLINIC: (
        "hospital consultation",
        "clinic diagnostic visit",
        "medical treatment bill",
    ),
    ClassificationSubcategoryCode.HEALTH_INSURANCE: (
        "health insurance premium",
        "medical policy renewal",
        "family health cover",
    ),
    ClassificationSubcategoryCode.TUITION_FEES: (
        "college tuition fee",
        "school semester fees",
        "academic institution fee",
    ),
    ClassificationSubcategoryCode.COURSES: (
        "online learning course",
        "professional certification class",
        "training programme enrollment",
    ),
    ClassificationSubcategoryCode.BOOKS_SUPPLIES: (
        "textbook and stationery",
        "academic books purchase",
        "education supplies",
    ),
    ClassificationSubcategoryCode.STREAMING: (
        "monthly video streaming subscription",
        "music streaming membership",
        "digital streaming plan",
    ),
    ClassificationSubcategoryCode.MOVIES_EVENTS: (
        "cinema movie tickets",
        "live event booking",
        "concert entry passes",
    ),
    ClassificationSubcategoryCode.GAMING: (
        "video game purchase",
        "gaming subscription",
        "online game credits",
    ),
    ClassificationSubcategoryCode.HOBBIES: (
        "art hobby supplies",
        "sports hobby equipment",
        "craft materials",
    ),
    ClassificationSubcategoryCode.EMI_LOAN_PAYMENT: (
        "monthly loan emi",
        "home loan repayment",
        "credit installment emi",
    ),
    ClassificationSubcategoryCode.BANK_CHARGES: (
        "bank service charges",
        "account maintenance fee",
        "debit card annual charge",
    ),
    ClassificationSubcategoryCode.TAXES: (
        "income tax payment",
        "municipal property tax",
        "government tax deposit",
    ),
    ClassificationSubcategoryCode.OTHER_INSURANCE: (
        "vehicle insurance premium",
        "term insurance renewal",
        "general insurance policy",
    ),
    ClassificationSubcategoryCode.SALARY: (
        "monthly salary payroll",
        "employer salary credit",
        "regular wages income",
    ),
    ClassificationSubcategoryCode.FREELANCE: (
        "freelance project income",
        "consulting work receipt",
        "independent contract payment",
    ),
    ClassificationSubcategoryCode.BUSINESS_INCOME: (
        "business sales income",
        "shop revenue receipt",
        "commercial service income",
    ),
    ClassificationSubcategoryCode.INTEREST: (
        "savings account interest",
        "deposit interest credit",
        "bank interest income",
    ),
    ClassificationSubcategoryCode.DIVIDEND: (
        "equity dividend credit",
        "company dividend income",
        "share dividend receipt",
    ),
    ClassificationSubcategoryCode.REFUND: (
        "merchant refund credit",
        "purchase reversal refund",
        "returned order refund",
    ),
    ClassificationSubcategoryCode.CASHBACK: (
        "reward cashback credit",
        "promotional cashback",
        "card cashback income",
    ),
    ClassificationSubcategoryCode.OTHER_INCOME: (
        "miscellaneous income receipt",
        "other personal income",
        "unclassified incoming credit",
    ),
    ClassificationSubcategoryCode.SELF_TRANSFER: (
        "transfer between own accounts",
        "internal account transfer",
        "self bank transfer",
    ),
    ClassificationSubcategoryCode.PERSON_TRANSFER: (
        "personal transfer received",
        "money sent to contact",
        "peer transfer",
    ),
    ClassificationSubcategoryCode.MUTUAL_FUND: (
        "mutual fund sip investment",
        "equity fund purchase",
        "monthly fund investment",
    ),
    ClassificationSubcategoryCode.STOCKS: (
        "stock broker investment",
        "equity share purchase",
        "securities trading debit",
    ),
    ClassificationSubcategoryCode.FIXED_DEPOSIT: (
        "fixed deposit investment",
        "term deposit booking",
        "bank deposit placement",
    ),
    ClassificationSubcategoryCode.RETIREMENT: (
        "retirement pension contribution",
        "provident fund investment",
        "retirement account deposit",
    ),
    ClassificationSubcategoryCode.OTHER_INVESTMENT: (
        "alternative investment contribution",
        "other asset investment",
        "investment account funding",
    ),
    ClassificationSubcategoryCode.ATM_WITHDRAWAL: (
        "atm cash withdrawal",
        "cash withdrawn from atm",
        "automated teller withdrawal",
    ),
    ClassificationSubcategoryCode.CASH_DEPOSIT: (
        "cash deposit branch",
        "cash deposited at bank",
        "cash machine deposit",
    ),
    ClassificationSubcategoryCode.UNCATEGORIZED: (
        "unrecognized expense entry",
        "unknown outgoing payment",
        "uncategorized debit",
    ),
    ClassificationSubcategoryCode.OTHER_EXPENSE: (
        "miscellaneous personal expense",
        "other spending payment",
        "general outgoing expense",
    ),
}

_BRAND_PREFIXES = (
    "Amber",
    "Aspen",
    "Cobalt",
    "Coral",
    "Ember",
    "Indigo",
    "Ivory",
    "Jade",
    "Lunar",
    "Maple",
    "Nimbus",
    "Opal",
    "Orchid",
    "Quartz",
    "River",
    "Saffron",
    "Silver",
    "Solar",
    "Teal",
    "Velvet",
    "Willow",
    "Zephyr",
)
_BRAND_SUFFIXES = (
    "Arc",
    "Bay",
    "Bloom",
    "Bridge",
    "Cove",
    "Field",
    "Grove",
    "Harbor",
    "Haven",
    "Leaf",
    "Nest",
    "Peak",
    "Point",
    "Spring",
    "Stone",
    "Trail",
    "Vale",
    "Vista",
    "Wave",
    "Works",
)


def build_reference_dataset() -> ClassificationDataset:
    """Return a balanced, all-leaf, synthetic reference dataset."""
    samples: list[LabeledFeatureSample] = []
    for label_index, subcategory in enumerate(ClassificationSubcategoryCode):
        category, definition = subcategory_definition(subcategory)
        transaction_type = _transaction_type(definition.transaction_types)
        for group_index in range(_GROUPS_PER_LABEL):
            brand_index = label_index * _GROUPS_PER_LABEL + group_index
            prefix = _BRAND_PREFIXES[brand_index % len(_BRAND_PREFIXES)]
            suffix_index = (
                brand_index // len(_BRAND_PREFIXES)
            ) % len(_BRAND_SUFFIXES)
            brand = f"{prefix} {_BRAND_SUFFIXES[suffix_index]}"
            for phrase_index, phrase in enumerate(_PHRASES[subcategory]):
                channel = _channel_prefix(subcategory, phrase_index)
                amount = Decimal(125 + (label_index * 173 + group_index * 41) % 24_000)
                if transaction_type is TransactionType.EXPENSE:
                    amount = -amount
                transaction_date = date(
                    2025 + (group_index % 2),
                    1 + ((label_index + group_index) % 12),
                    1 + ((label_index * 3 + phrase_index * 7) % 27),
                )
                features = build_classification_features(
                    TransactionFeatureInput(
                        description=f"{channel} {brand} {phrase}",
                        merchant_name=brand,
                        transaction_type=transaction_type,
                        signed_amount=amount,
                        transaction_date=transaction_date,
                        account_currency="INR",
                    )
                )
                samples.append(
                    LabeledFeatureSample(
                        source_key=(
                            f"synthetic:{subcategory.value}:{group_index}:"
                            f"{phrase_index}"
                        ),
                        group_key=f"synthetic:{subcategory.value}:{group_index}",
                        features=features,
                        category=category,
                        subcategory=subcategory,
                        merchant_group=True,
                    )
                )
    return build_classification_dataset(
        samples,
        group_secret=_SYNTHETIC_SECRET,
        source_kind=DatasetSourceKind.SYNTHETIC,
    )


def _transaction_type(
    allowed: frozenset[TransactionType],
) -> TransactionType:
    for preferred in (
        TransactionType.EXPENSE,
        TransactionType.INCOME,
        TransactionType.TRANSFER,
    ):
        if preferred in allowed:
            return preferred
    raise RuntimeError("Synthetic taxonomy target has no transaction type.")


def _channel_prefix(
    subcategory: ClassificationSubcategoryCode,
    phrase_index: int,
) -> str:
    if subcategory is ClassificationSubcategoryCode.ATM_WITHDRAWAL:
        return "ATM"
    if subcategory is ClassificationSubcategoryCode.CASH_DEPOSIT:
        return "CASH"
    return ("UPI", "POS", "NEFT")[phrase_index]


def main() -> None:
    """Generate reviewed files without writing a serialized estimator."""
    repository_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=repository_root / "data" / "synthetic" / "classification",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=repository_root
        / "ml"
        / "reports"
        / "classification_evaluation_2026_1.json",
    )
    arguments = parser.parse_args()

    dataset = build_reference_dataset()
    comparison = compare_classification_models(dataset)
    arguments.output_directory.mkdir(parents=True, exist_ok=True)
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    (arguments.output_directory / "transactions_2026_1.jsonl").write_text(
        dataset.records_jsonl(), encoding="utf-8", newline="\n"
    )
    (arguments.output_directory / "manifest_2026_1.json").write_text(
        json.dumps(
            dataset.manifest.to_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    arguments.report.write_text(
        comparison.report.to_json(), encoding="utf-8", newline="\n"
    )
    print(
        f"Built {dataset.manifest.record_count} records; selected "
        f"{comparison.report.selected_candidate.value}."
    )


if __name__ == "__main__":
    main()
