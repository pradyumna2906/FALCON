"""Deterministic CPU XGBoost candidate with recursive leakage-safe features."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from importlib import import_module

from falcon_api.forecasting.candidates import (
    ForecastCandidateFitError,
    ForecastCandidateUnavailableError,
    normalize_candidate_predictions,
    validate_candidate_request,
)
from falcon_api.forecasting.features import (
    ForecastFeatureSpec,
    build_feature_vector,
    build_supervised_feature_matrix,
    feature_spec_for,
)
from falcon_api.forecasting.semantics import ForecastGranularity


@dataclass(frozen=True, slots=True)
class XGBoostCandidate:
    """A bounded, reproducible lag-feature regression candidate."""

    granularity: ForecastGranularity
    estimators: int = 64
    maximum_depth: int = 3
    learning_rate: float = 0.05
    random_state: int = 2026

    def __post_init__(self) -> None:
        object.__setattr__(self, "granularity", ForecastGranularity(self.granularity))
        if isinstance(self.estimators, bool) or self.estimators <= 0:
            raise ValueError("XGBoost estimators must be positive.")
        if isinstance(self.maximum_depth, bool) or self.maximum_depth <= 0:
            raise ValueError("XGBoost depth must be positive.")
        if not 0 < self.learning_rate <= 1:
            raise ValueError("XGBoost learning rate must be in (0, 1].")

    @property
    def code(self) -> str:
        return f"xgboost_lagged_{self.granularity.value}"

    @property
    def feature_spec(self) -> ForecastFeatureSpec:
        return feature_spec_for(self.granularity)

    @property
    def minimum_training_points(self) -> int:
        return self.feature_spec.minimum_history_points + 8

    def predict(
        self, training_values: tuple[Decimal, ...], horizon: int
    ) -> tuple[Decimal, ...]:
        validate_candidate_request(
            training_values, horizon, self.minimum_training_points
        )
        matrix = build_supervised_feature_matrix(
            values=training_values, spec=self.feature_spec
        )
        try:
            regressor_type = import_module("xgboost").XGBRegressor
        except (ImportError, ModuleNotFoundError) as exc:
            raise ForecastCandidateUnavailableError(
                "CPU XGBoost dependency is unavailable."
            ) from exc
        try:
            model = regressor_type(
                objective="reg:squarederror",
                n_estimators=self.estimators,
                max_depth=self.maximum_depth,
                learning_rate=self.learning_rate,
                subsample=1.0,
                colsample_bytree=1.0,
                random_state=self.random_state,
                n_jobs=1,
                tree_method="hist",
                verbosity=0,
            )
            model.fit(matrix.features, matrix.targets)
            recursive_history = list(training_values)
            raw_predictions: list[float] = []
            for _ in range(horizon):
                vector = build_feature_vector(
                    history=tuple(recursive_history), spec=self.feature_spec
                )
                predicted = float(model.predict((vector.values,))[0])
                raw_predictions.append(predicted)
                recursive_history.append(Decimal(str(predicted)))
            return normalize_candidate_predictions(raw_predictions, horizon=horizon)
        except ForecastCandidateFitError:
            raise
        except Exception as exc:
            raise ForecastCandidateFitError("XGBoost fitting failed safely.") from exc
