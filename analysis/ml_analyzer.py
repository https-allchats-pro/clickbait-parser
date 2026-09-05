from __future__ import annotations

from analysis.analyzer import DEFAULT_CLICKBAIT_THRESHOLD
from analysis.models import ClickbaitAnalysis, ClickbaitFeatures
from app.ml.predictor import MLPredictor
from app.ml.storage import ModelStore
from domain.ml import MLModelNotFoundError
from domain.posts import CatalogPost


class MLClickbaitAnalyzer:
    """PostAnalyzer backed by the saved TF-IDF + LogisticRegression model."""

    def __init__(
        self,
        *,
        store: ModelStore | None = None,
        predictor: MLPredictor | None = None,
        threshold: float = DEFAULT_CLICKBAIT_THRESHOLD,
    ) -> None:
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be between 0.0 and 1.0")
        self.threshold = float(threshold)
        self._predictor = predictor or MLPredictor(store or ModelStore())

    def analyze(self, post: CatalogPost) -> ClickbaitAnalysis:
        if post.id is None:
            raise ValueError("CatalogPost.id (local SQLite id) is required for analysis")
        if not self._predictor.is_ready():
            raise MLModelNotFoundError("Model is not trained yet.")

        score = self._predictor.predict_proba_clickbait(post.text or "")
        score = min(max(float(score), 0.0), 1.0)
        return ClickbaitAnalysis(
            post_id=int(post.id),
            score=score,
            is_clickbait=score >= self.threshold,
            reasons=["ml_tfidf_logreg"],
            features=ClickbaitFeatures(),
        )
