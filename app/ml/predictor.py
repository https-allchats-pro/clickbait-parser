from __future__ import annotations

from typing import Any

from app.ml.storage import ModelStore
from app.ml.trainer import predict_proba_clickbait
from domain.ml import MLModelNotFoundError


class MLPredictor:
    """Loads the saved sklearn bundle and scores post texts."""

    def __init__(self, store: ModelStore | None = None) -> None:
        self._store = store or ModelStore()
        self._vectorizer: Any | None = None
        self._classifier: Any | None = None

    def is_ready(self) -> bool:
        return self._store.exists()

    def reload(self) -> None:
        bundle = self._store.load_bundle()
        self._vectorizer = bundle["vectorizer"]
        self._classifier = bundle["classifier"]

    def ensure_loaded(self) -> None:
        if self._vectorizer is None or self._classifier is None:
            self.reload()

    def predict_proba_clickbait(self, text: str) -> float:
        if not self.is_ready():
            raise MLModelNotFoundError("Model is not trained yet.")
        self.ensure_loaded()
        assert self._vectorizer is not None
        assert self._classifier is not None
        return predict_proba_clickbait(
            vectorizer=self._vectorizer,
            classifier=self._classifier,
            text=text,
        )
