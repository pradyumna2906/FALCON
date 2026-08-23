"""Privacy and cardinality tests for classification monitoring."""

import json
import logging
from decimal import Decimal
from uuid import uuid4

import pytest

from falcon_api.classification.monitoring import (
    ClassificationMonitor,
    ClassificationOperation,
)
from falcon_api.classification.taxonomy import (
    ClassificationCategoryCode,
    ClassificationSubcategoryCode,
)
from falcon_api.classification.types import (
    ClassificationDecision,
    ClassificationReasonCode,
    ClassificationSource,
)
from falcon_api.core.logging import JsonLogFormatter
from falcon_api.schemas.classification import ClassificationResult


def _result(
    decision: ClassificationDecision,
    reason: ClassificationReasonCode,
) -> ClassificationResult:
    classified = decision is not ClassificationDecision.ABSTAINED
    return ClassificationResult(
        transaction_id=uuid4(),
        decision=decision,
        source=ClassificationSource.ML,
        category_code=(
            ClassificationCategoryCode.FOOD_DINING if classified else None
        ),
        subcategory_code=(
            ClassificationSubcategoryCode.RESTAURANTS if classified else None
        ),
        confidence=Decimal("0.7200") if classified else Decimal("0.3000"),
        reason_codes=(reason,),
        model_version="classification_test.1",
    )


def test_classification_monitor_emits_only_aggregate_closed_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    times = iter((10.0, 10.125))
    logger = logging.getLogger("test.classification.monitor")
    monitor = ClassificationMonitor(logger=logger, timer=lambda: next(times))
    results = (
        _result(
            ClassificationDecision.SUGGESTED,
            ClassificationReasonCode.MODEL_PREDICTION,
        ),
        _result(
            ClassificationDecision.ABSTAINED,
            ClassificationReasonCode.LOW_CONFIDENCE,
        ),
    )

    with caplog.at_level(logging.INFO, logger=logger.name):
        started_at = monitor.start()
        monitor.record_classification(results, started_at=started_at)

    record = caplog.records[-1]
    payload = json.loads(JsonLogFormatter().format(record))
    assert payload["event"] == "classification_operation_completed"
    assert payload["classification_operation"] == "classify"
    assert payload["classification_item_count"] == 2
    assert payload["classification_decision_counts"] == {
        "abstained": 1,
        "suggested": 1,
    }
    assert payload["classification_source_counts"] == {"ml": 2}
    assert payload["classification_reason_counts"] == {
        "low_confidence": 1,
        "model_prediction": 1,
    }
    assert payload["classification_taxonomy_version"] == "2026.1"
    assert payload["duration_ms"] == 125.0
    rendered = json.dumps(payload)
    for forbidden in (
        "user_id",
        "transaction_id",
        "merchant",
        "description",
        "feature",
        str(results[0].transaction_id),
    ):
        assert forbidden not in rendered


def test_non_classification_operations_are_bounded() -> None:
    times = iter((20.0, 20.01))
    monitor = ClassificationMonitor(timer=lambda: next(times))
    started_at = monitor.start()

    monitor.record_operation(
        ClassificationOperation.MERCHANT_MEMORY_LIST,
        item_count=100,
        started_at=started_at,
    )
    with pytest.raises(ValueError, match="zero and 100"):
        monitor.record_operation(
            ClassificationOperation.CORRECT,
            item_count=101,
            started_at=started_at,
        )
    with pytest.raises(ValueError, match="record_classification"):
        monitor.record_operation(
            ClassificationOperation.CLASSIFY,
            item_count=1,
            started_at=started_at,
        )


def test_classification_monitor_rejects_an_empty_observation() -> None:
    monitor = ClassificationMonitor()

    with pytest.raises(ValueError, match="one through 100"):
        monitor.record_classification((), started_at=monitor.start())
