from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.ml.storage import ModelStore
from app.ml.trainer import LABEL_CLICKBAIT
from domain.ml import MLModelNotFoundError, ModelInfo

DEFAULT_TOP_N = 15


@dataclass(frozen=True)
class ModelFeature:
    """One TF-IDF term with its LogisticRegression coefficient (CLICKBAIT direction)."""

    term: str
    coefficient: float


class ModelInsightsError(RuntimeError):
    """Saved model cannot be interpreted for feature insights."""


class ModelInsightsService:
    """Extract TF-IDF feature coefficients from the saved sklearn artifact.

    Positive coefficients are associated with CLICKBAIT; negative with NORMAL.
    """

    def __init__(self, store: ModelStore | None = None) -> None:
        self._store = store or ModelStore()

    @property
    def store(self) -> ModelStore:
        return self._store

    def is_ready(self) -> bool:
        return self._store.exists()

    def get_model_info(self) -> ModelInfo | None:
        return self._store.load_info()

    def list_feature_coefficients(self) -> list[ModelFeature]:
        """Return all features with coefficients oriented so + = CLICKBAIT."""
        names, coefs = self._load_names_and_coefs()
        return [
            ModelFeature(term=str(name), coefficient=float(coef))
            for name, coef in zip(names, coefs, strict=True)
        ]

    def get_top_clickbait_features(self, limit: int = DEFAULT_TOP_N) -> list[ModelFeature]:
        """Highest positive coefficients first (associated with CLICKBAIT)."""
        n = max(0, int(limit))
        positives = [f for f in self.list_feature_coefficients() if f.coefficient > 0]
        positives.sort(key=lambda f: f.coefficient, reverse=True)
        return positives[:n]

    def get_top_normal_features(self, limit: int = DEFAULT_TOP_N) -> list[ModelFeature]:
        """Most negative coefficients first (associated with NORMAL)."""
        n = max(0, int(limit))
        negatives = [f for f in self.list_feature_coefficients() if f.coefficient < 0]
        negatives.sort(key=lambda f: f.coefficient)  # ascending: -2.3 before -1.1
        return negatives[:n]

    def _load_names_and_coefs(self) -> tuple[list[str], list[float]]:
        if not self._store.exists():
            raise MLModelNotFoundError("Model is not trained yet.")
        try:
            bundle = self._store.load_bundle()
        except MLModelNotFoundError:
            raise
        except Exception as exc:
            raise ModelInsightsError(f"Cannot load model artifact: {exc}") from exc

        vectorizer = bundle.get("vectorizer")
        classifier = bundle.get("classifier")
        if vectorizer is None or classifier is None:
            raise ModelInsightsError("Model artifact is missing vectorizer/classifier.")

        try:
            names = list(vectorizer.get_feature_names_out())
        except Exception as exc:
            raise ModelInsightsError(
                f"Vectorizer does not expose feature names: {exc}"
            ) from exc

        try:
            coefs = self._clickbait_oriented_coefs(classifier, n_features=len(names))
        except ModelInsightsError:
            raise
        except Exception as exc:
            raise ModelInsightsError(
                f"Cannot read LogisticRegression coefficients: {exc}"
            ) from exc

        if len(coefs) != len(names):
            raise ModelInsightsError(
                f"Feature/coefficient length mismatch: "
                f"{len(names)} features vs {len(coefs)} coefficients."
            )
        return names, coefs

    @staticmethod
    def _clickbait_oriented_coefs(classifier: Any, *, n_features: int) -> list[float]:
        if not hasattr(classifier, "coef_"):
            raise ModelInsightsError("Classifier has no coef_ attribute.")
        coef = classifier.coef_
        if coef is None:
            raise ModelInsightsError("Classifier coef_ is empty.")

        classes = list(getattr(classifier, "classes_", []))
        if not classes:
            raise ModelInsightsError("Classifier has no classes_.")

        # Binary LR: coef_ shape (1, n_features) scores classes_[1].
        # Multiclass: one row per class.
        try:
            shape = getattr(coef, "shape", None)
            if shape is None or len(shape) != 2:
                raise ModelInsightsError("Unexpected coef_ shape.")
            if shape[1] != n_features and shape[0] != n_features:
                # Allow only (n_classes, n_features)
                if shape[1] != n_features:
                    raise ModelInsightsError(
                        f"coef_ width {shape[1]} != feature count {n_features}."
                    )

            if shape[0] == 1 and len(classes) == 2:
                row = [float(x) for x in coef[0]]
                # Positive class is classes_[1]; flip if that is not CLICKBAIT.
                if classes[1] == LABEL_CLICKBAIT:
                    return row
                if classes[0] == LABEL_CLICKBAIT:
                    return [-x for x in row]
                raise ModelInsightsError(
                    f"CLICKBAIT class {LABEL_CLICKBAIT} not in {classes}."
                )

            if LABEL_CLICKBAIT not in classes:
                raise ModelInsightsError(
                    f"CLICKBAIT class {LABEL_CLICKBAIT} not in {classes}."
                )
            idx = classes.index(LABEL_CLICKBAIT)
            return [float(x) for x in coef[idx]]
        except ModelInsightsError:
            raise
        except Exception as exc:
            raise ModelInsightsError(f"Malformed classifier coefficients: {exc}") from exc
