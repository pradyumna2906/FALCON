"""Rules-first hybrid transaction classification with safe abstention."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from falcon_api.classification.features import ClassificationFeatures
from falcon_api.classification.inference import TransactionClassifier
from falcon_api.classification.rules import ClassificationRulesEngine, RuleEvaluation
from falcon_api.classification.taxonomy import (
    CLASSIFICATION_TAXONOMY_VERSION,
    ClassificationCategoryCode,
    ClassificationSubcategoryCode,
    validate_classification_target,
)
from falcon_api.classification.types import (
    ClassificationDecision,
    ClassificationReasonCode,
    ClassificationSource,
)


class ClassifierProvider(Protocol):
    """Minimal lazy-provider boundary used by hybrid classification."""

    model_version: str

    def get_classifier(self) -> TransactionClassifier:
        """Return a verified cached classifier or raise a bounded error."""


@dataclass(frozen=True, slots=True)
class HybridClassificationOutcome:
    """Persistence-ready result without transaction ownership or raw features."""

    decision: ClassificationDecision
    source: ClassificationSource
    category: ClassificationCategoryCode | None
    subcategory: ClassificationSubcategoryCode | None
    confidence: Decimal
    reason_codes: tuple[ClassificationReasonCode, ...]
    taxonomy_version: str = CLASSIFICATION_TAXONOMY_VERSION
    ruleset_version: str | None = None
    model_version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.decision, ClassificationDecision):
            raise TypeError("decision must be a classification decision.")
        if not isinstance(self.source, ClassificationSource):
            raise TypeError("source must be a classification source.")
        if self.taxonomy_version != CLASSIFICATION_TAXONOMY_VERSION:
            raise ValueError("The outcome taxonomy version is incompatible.")
        if (
            not isinstance(self.confidence, Decimal)
            or not self.confidence.is_finite()
            or not Decimal(0) <= self.confidence <= Decimal(1)
        ):
            raise ValueError("Outcome confidence must be an exact decimal in [0, 1].")
        if not self.reason_codes or len(self.reason_codes) > 5:
            raise ValueError("An outcome requires one through five reason codes.")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("Outcome reason codes must be unique.")
        has_target = self.category is not None and self.subcategory is not None
        if self.decision is ClassificationDecision.ABSTAINED:
            if self.category is not None or self.subcategory is not None:
                raise ValueError("An abstained outcome cannot assign a target.")
        elif not has_target:
            raise ValueError("A classified outcome requires a complete target.")
        else:
            validate_classification_target(
                category=self.category,
                subcategory=self.subcategory,
            )
        uses_rules = self.source in {
            ClassificationSource.RULE,
            ClassificationSource.HYBRID,
        }
        uses_model = self.source in {
            ClassificationSource.ML,
            ClassificationSource.HYBRID,
        }
        if uses_rules != (self.ruleset_version is not None):
            raise ValueError("Rule outcomes require exactly one ruleset version.")
        if uses_model != (self.model_version is not None):
            raise ValueError("Model outcomes require exactly one model version.")
        for version in (self.ruleset_version, self.model_version):
            if version is not None and (not version or len(version) > 64):
                raise ValueError("Outcome provenance versions must be bounded.")


@dataclass(frozen=True, slots=True)
class MerchantMemoryMatch:
    """One same-user exact merchant mapping resolved from trusted storage."""

    category: ClassificationCategoryCode
    subcategory: ClassificationSubcategoryCode

    def __post_init__(self) -> None:
        validate_classification_target(
            category=self.category,
            subcategory=self.subcategory,
        )


class HybridClassificationService:
    """Apply reviewed rules first, then verified calibrated ML when needed."""

    def __init__(
        self,
        *,
        classifier_provider: ClassifierProvider,
        rules_engine: ClassificationRulesEngine | None = None,
    ) -> None:
        if not hasattr(classifier_provider, "model_version") or not callable(
            getattr(classifier_provider, "get_classifier", None)
        ):
            raise TypeError("classifier_provider does not implement the contract.")
        if (
            not isinstance(classifier_provider.model_version, str)
            or not classifier_provider.model_version
            or len(classifier_provider.model_version) > 64
        ):
            raise ValueError("classifier_provider has an invalid model version.")
        self._provider = classifier_provider
        self._rules = rules_engine or ClassificationRulesEngine()

    def classify(
        self,
        features: ClassificationFeatures,
        *,
        merchant_memory: MerchantMemoryMatch | None = None,
    ) -> HybridClassificationOutcome:
        """Apply global rules, same-user exact memory, then calibrated ML."""
        if not isinstance(features, ClassificationFeatures):
            raise TypeError("features must use the shared classification schema.")
        if merchant_memory is not None and not isinstance(
            merchant_memory, MerchantMemoryMatch
        ):
            raise TypeError("merchant_memory must use the trusted match contract.")
        rules = self._rules.evaluate(features)
        if rules.selected is not None:
            selected = rules.selected
            return HybridClassificationOutcome(
                decision=ClassificationDecision.AUTOMATIC,
                source=ClassificationSource.RULE,
                category=selected.category,
                subcategory=selected.subcategory,
                confidence=selected.confidence,
                reason_codes=(selected.reason_code,),
                ruleset_version=rules.ruleset_version,
            )
        if merchant_memory is not None:
            try:
                validate_classification_target(
                    category=merchant_memory.category,
                    subcategory=merchant_memory.subcategory,
                    transaction_type=features.transaction_type,
                )
            except ValueError:
                pass
            else:
                return HybridClassificationOutcome(
                    decision=ClassificationDecision.AUTOMATIC,
                    source=ClassificationSource.MERCHANT_MEMORY,
                    category=merchant_memory.category,
                    subcategory=merchant_memory.subcategory,
                    confidence=Decimal("1.0000"),
                    reason_codes=(ClassificationReasonCode.USER_MERCHANT_MEMORY,),
                )
        return self._classify_with_model(features, rules)

    def _classify_with_model(
        self,
        features: ClassificationFeatures,
        rules: RuleEvaluation,
    ) -> HybridClassificationOutcome:
        source = (
            ClassificationSource.HYBRID if rules.conflicted else ClassificationSource.ML
        )
        try:
            classifier = self._provider.get_classifier()
            prediction = classifier.predict(features)
            if (
                prediction.model_version != self._provider.model_version
                or classifier.metadata.model_version != self._provider.model_version
                or prediction.production_eligible
                != classifier.metadata.production_eligible
            ):
                raise ValueError("Classifier version identity mismatch.")
        except Exception:
            reasons = (
                (
                    ClassificationReasonCode.AMBIGUOUS_PREDICTION,
                    ClassificationReasonCode.CLASSIFIER_UNAVAILABLE,
                )
                if rules.conflicted
                else (ClassificationReasonCode.CLASSIFIER_UNAVAILABLE,)
            )
            return self._abstained(
                source=source,
                confidence=Decimal(0),
                reason_codes=reasons,
                rules=rules,
            )

        selected = prediction.selected
        try:
            validate_classification_target(
                category=selected.category,
                subcategory=selected.subcategory,
                transaction_type=features.transaction_type,
            )
        except ValueError:
            return self._abstained(
                source=source,
                confidence=prediction.confidence,
                reason_codes=(ClassificationReasonCode.UNSUPPORTED_TRANSACTION_TYPE,),
                rules=rules,
                model_version=prediction.model_version,
            )

        reasons = [ClassificationReasonCode.MODEL_PREDICTION]
        if rules.conflicted:
            top_priority = max(match.priority for match in rules.matches)
            leading_targets = {
                (match.category, match.subcategory)
                for match in rules.matches
                if match.priority == top_priority
            }
            if (selected.category, selected.subcategory) not in leading_targets:
                return self._abstained(
                    source=source,
                    confidence=prediction.confidence,
                    reason_codes=(ClassificationReasonCode.AMBIGUOUS_PREDICTION,),
                    rules=rules,
                    model_version=prediction.model_version,
                )
            reasons.append(ClassificationReasonCode.RULE_MODEL_AGREEMENT)

        policy = classifier.metadata.confidence_policy
        if prediction.top_two_margin < policy.minimum_top_two_margin:
            return self._abstained(
                source=source,
                confidence=prediction.confidence,
                reason_codes=(ClassificationReasonCode.AMBIGUOUS_PREDICTION,),
                rules=rules,
                model_version=prediction.model_version,
            )
        if prediction.confidence < policy.suggestion_confidence:
            return self._abstained(
                source=source,
                confidence=prediction.confidence,
                reason_codes=(ClassificationReasonCode.LOW_CONFIDENCE,),
                rules=rules,
                model_version=prediction.model_version,
            )

        if not prediction.production_eligible:
            reasons.append(ClassificationReasonCode.PROVISIONAL_MODEL)
            decision = ClassificationDecision.SUGGESTED
        elif prediction.confidence >= policy.automatic_confidence:
            decision = ClassificationDecision.AUTOMATIC
        else:
            decision = ClassificationDecision.SUGGESTED
        return HybridClassificationOutcome(
            decision=decision,
            source=source,
            category=selected.category,
            subcategory=selected.subcategory,
            confidence=prediction.confidence,
            reason_codes=tuple(reasons),
            ruleset_version=rules.ruleset_version if rules.conflicted else None,
            model_version=prediction.model_version,
        )

    def _abstained(
        self,
        *,
        source: ClassificationSource,
        confidence: Decimal,
        reason_codes: tuple[ClassificationReasonCode, ...],
        rules: RuleEvaluation,
        model_version: str | None = None,
    ) -> HybridClassificationOutcome:
        return HybridClassificationOutcome(
            decision=ClassificationDecision.ABSTAINED,
            source=source,
            category=None,
            subcategory=None,
            confidence=confidence,
            reason_codes=reason_codes,
            ruleset_version=rules.ruleset_version if rules.conflicted else None,
            model_version=model_version or self._provider.model_version,
        )
