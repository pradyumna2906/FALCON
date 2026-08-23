"""Minimal structured logging configuration for container collection."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

_MANAGED_HANDLER = "_falcon_structured_handler"
_STRUCTURED_FIELDS = (
    "request_id",
    "http_method",
    "http_path",
    "http_status",
    "duration_ms",
    "error_type",
    "stack",
    "classification_operation",
    "classification_item_count",
    "classification_decision_counts",
    "classification_source_counts",
    "classification_reason_counts",
    "classification_taxonomy_version",
)


class JsonLogFormatter(logging.Formatter):
    """Serialize only approved operational fields as one JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for field in _STRUCTURED_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def configure_logging() -> None:
    """Install one safe stdout logger and suppress duplicate access logs."""
    logging.getLogger("uvicorn.access").disabled = True

    falcon_logger = logging.getLogger("falcon_api")
    falcon_logger.setLevel(logging.INFO)
    falcon_logger.propagate = False

    if any(
        getattr(handler, _MANAGED_HANDLER, False)
        for handler in falcon_logger.handlers
    ):
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    setattr(handler, _MANAGED_HANDLER, True)
    falcon_logger.addHandler(handler)
