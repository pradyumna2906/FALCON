"""Verify the real FastAPI classifier wiring without accessing a database."""

from __future__ import annotations
import argparse
import json
from pathlib import Path
from datetime import date
from decimal import Decimal

from falcon_api.classification.features import (
    TransactionFeatureInput,
    build_classification_features,
)
from falcon_api.classification.types import (
    ClassificationReasonCode,
    ClassificationDecision,
)
from falcon_api.core.config import Settings, AppEnvironment
from falcon_api.main import create_app
from falcon_api.models.enums import TransactionType


def verify(registry: Path, version: str):
    application = create_app(
        Settings(
            env=AppEnvironment.TEST,
            debug=False,
            classification_artifact_root=registry,
            classification_model_version=version,
        )
    )
    hybrid = application.state.classification_service._hybrid
    provider = hybrid._provider
    assert not provider.is_loaded
    features = build_classification_features(
        TransactionFeatureInput(
            description="UPI synthetic merchant payment processed",
            merchant_name=None,
            transaction_type=TransactionType.EXPENSE,
            signed_amount=Decimal("-500"),
            transaction_date=date(2026, 9, 1),
            account_currency="INR",
        )
    )
    result = hybrid.classify(features)
    assert provider.is_loaded, "FastAPI did not load the configured model"
    assert ClassificationReasonCode.CLASSIFIER_UNAVAILABLE not in result.reason_codes
    assert result.model_version == version
    assert not provider.get_classifier().metadata.production_eligible
    assert result.decision != ClassificationDecision.AUTOMATIC
    assert provider.get_classifier() is provider.get_classifier()
    return {
        "application_factory_wiring_verified": True,
        "lazy_load_verified": True,
        "cached_instance_verified": True,
        "model_version": version,
        "decision": result.decision.value,
        "source": result.source.value,
        "subcategory": result.subcategory.value if result.subcategory else None,
        "synthetic_automatic_assignment_blocked": True,
        "database_or_http_flow_evaluated": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry", type=Path, default=Path("ml/artifacts/classification")
    )
    parser.add_argument("--version", default="classification_2026_3_review.1")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = verify(args.registry, args.version)
    payload = json.dumps(result, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload, encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
