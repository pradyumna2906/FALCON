"""Privacy-safe aggregate operational monitoring for classification."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Iterable
from enum import StrEnum
from time import perf_counter
from typing import Protocol

from falcon_api.classification.types import (
    ClassificationDecision,
    ClassificationReasonCode,
    ClassificationSource,
)


class ClassificationOperation(StrEnum):
    """Closed operation names safe for low-cardinality monitoring."""

    CLASSIFY = "classify"
    CORRECT = "correct"
    MERCHANT_MEMORY_UPSERT = "merchant_memory_upsert"
    MERCHANT_MEMORY_LIST = "merchant_memory_list"
    MERCHANT_MEMORY_DELETE = "merchant_memory_delete"


class ClassificationObservation(Protocol):
    """Minimum aggregate-safe result surface consumed by the monitor."""

    decision: ClassificationDecision
    source: ClassificationSource
    reason_codes: tuple[ClassificationReasonCode, ...]
    taxonomy_version: str


class ClassificationMonitor:
    """Emit bounded counts and timings without identifiers or input content."""

    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        timer: Callable[[], float] = perf_counter,
    ) -> None:
        self._logger = logger or logging.getLogger("falcon_api.classification")
        self._timer = timer

    def start(self) -> float:
        """Capture a monotonic start time for one operation."""
        return self._timer()

    def record_classification(
        self,
        results: Iterable[ClassificationObservation],
        *,
        started_at: float,
    ) -> None:
        """Emit one aggregate event for a successful single or batch request."""
        items = tuple(results)
        if not items or len(items) > 100:
            raise ValueError(
                "classification results must contain one through 100 items."
            )
        versions = {item.taxonomy_version for item in items}
        taxonomy_version = next(iter(versions)) if len(versions) == 1 else "mixed"
        self._emit(
            operation=ClassificationOperation.CLASSIFY,
            item_count=len(items),
            started_at=started_at,
            decision_counts=_enum_counts(item.decision for item in items),
            source_counts=_enum_counts(item.source for item in items),
            reason_counts=_enum_counts(
                reason for item in items for reason in item.reason_codes
            ),
            taxonomy_version=taxonomy_version,
        )

    def record_operation(
        self,
        operation: ClassificationOperation,
        *,
        item_count: int,
        started_at: float,
    ) -> None:
        """Emit one bounded event for a successful correction or memory action."""
        if operation is ClassificationOperation.CLASSIFY:
            raise ValueError("Use record_classification for classification results.")
        if item_count < 0 or item_count > 100:
            raise ValueError("classification item_count must be between zero and 100.")
        self._emit(
            operation=operation,
            item_count=item_count,
            started_at=started_at,
        )

    def _emit(
        self,
        *,
        operation: ClassificationOperation,
        item_count: int,
        started_at: float,
        decision_counts: dict[str, int] | None = None,
        source_counts: dict[str, int] | None = None,
        reason_counts: dict[str, int] | None = None,
        taxonomy_version: str | None = None,
    ) -> None:
        duration_ms = max(0.0, (self._timer() - started_at) * 1000)
        self._logger.info(
            "classification_operation_completed",
            extra={
                "classification_operation": operation.value,
                "classification_item_count": item_count,
                "classification_decision_counts": decision_counts,
                "classification_source_counts": source_counts,
                "classification_reason_counts": reason_counts,
                "classification_taxonomy_version": taxonomy_version,
                "duration_ms": round(duration_ms, 3),
            },
        )


def _enum_counts(values: Iterable[StrEnum]) -> dict[str, int]:
    """Build deterministic low-cardinality counts from closed enums."""
    return dict(sorted(Counter(item.value for item in values).items()))
