"""Shared validation and output normalization for forecast model adapters."""

from __future__ import annotations

from decimal import Decimal
from math import isfinite
from typing import Iterable

from falcon_api.analytics.types import money


class ForecastCandidateError(ValueError):
    """Base error for a candidate that cannot produce a safe forecast."""


class ForecastCandidateUnavailableError(ForecastCandidateError):
    """The optional candidate dependency is not available."""


class ForecastCandidateFitError(ForecastCandidateError):
    """A candidate could not fit or predict safely for the supplied history."""


def validate_candidate_request(
    training_values: tuple[Decimal, ...], horizon: int, minimum: int
) -> None:
    if len(training_values) < minimum:
        raise ForecastCandidateError("Candidate requires more training observations.")
    if isinstance(horizon, bool) or horizon <= 0:
        raise ForecastCandidateError("Prediction horizon must be positive.")
    if any(not value.is_finite() for value in training_values):
        raise ForecastCandidateError("Training values must be finite.")


def normalize_candidate_predictions(
    values: Iterable[float], *, horizon: int
) -> tuple[Decimal, ...]:
    resolved = tuple(float(value) for value in values)
    if len(resolved) != horizon or any(not isfinite(value) for value in resolved):
        raise ForecastCandidateFitError("Candidate returned unsafe predictions.")
    return tuple(money(Decimal(str(value))) for value in resolved)
