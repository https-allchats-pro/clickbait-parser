from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from app.ml.predictor import MLPredictor
from app.ml.storage import ModelStore
from app.ml.trainer import LABEL_CLICKBAIT, LABEL_NORMAL, train_tfidf_logreg
from domain.dataset import DatasetLabel
from domain.ml import MLTrainingError, ModelInfo, TrainingResult
from domain.posts import CatalogPost


class PostReader(Protocol):
    def get_by_id(self, post_id: int) -> CatalogPost | None: ...


class LabelReader(Protocol):
    def list_all(self, limit: int | None = None): ...

    def count_by_label(self) -> dict[DatasetLabel, int]: ...


class MLTrainingService:
    """Train / inspect TF-IDF + LogisticRegression on human labels only."""

    def __init__(
        self,
        *,
        posts: PostReader,
        labels: LabelReader,
        store: ModelStore | None = None,
    ) -> None:
        self._posts = posts
        self._labels = labels
        self._store = store or ModelStore()

    @property
    def store(self) -> ModelStore:
        return self._store

    def load_training_pairs(self) -> tuple[list[str], list[int]]:
        """Return (texts, y) from human labels. BORDERLINE excluded.

        Target is ``post_labels.label`` only — never ``post_analysis``.
        """
        texts: list[str] = []
        y: list[int] = []
        for label in self._labels.list_all():
            if label.label == DatasetLabel.BORDERLINE:
                continue
            if label.label == DatasetLabel.CLICKBAIT:
                cls = LABEL_CLICKBAIT
            elif label.label == DatasetLabel.NORMAL:
                cls = LABEL_NORMAL
            else:
                continue
            post = self._posts.get_by_id(label.post_id)
            if post is None:
                continue
            texts.append(post.text or "")
            y.append(cls)
        return texts, y

    def train(self) -> TrainingResult:
        texts, y = self.load_training_pairs()
        n_clickbait = sum(1 for v in y if v == LABEL_CLICKBAIT)
        n_normal = sum(1 for v in y if v == LABEL_NORMAL)
        if n_clickbait < 1 or n_normal < 1:
            raise MLTrainingError(
                "Not enough labeled data for training.\n"
                "Need at least one CLICKBAIT and one NORMAL post."
            )

        fitted = train_tfidf_logreg(texts, y)
        version = self._store.next_version()
        info = ModelInfo(
            version=version,
            trained_at=datetime.now(tz=UTC),
            metrics=fitted.metrics,
            label_count_at_train=n_clickbait + n_normal,
        )
        path = self._store.save(
            vectorizer=fitted.vectorizer,
            classifier=fitted.classifier,
            info=info,
        )
        return TrainingResult(info=info, model_path=str(path))

    def get_model_info(self) -> ModelInfo | None:
        return self._store.load_info()

    def binary_label_count(self) -> int:
        counts = self._labels.count_by_label()
        return int(counts[DatasetLabel.CLICKBAIT] + counts[DatasetLabel.NORMAL])

    def new_labels_since_train(self) -> int:
        info = self.get_model_info()
        current = self.binary_label_count()
        if info is None:
            return current
        return max(0, current - int(info.label_count_at_train))

    def make_predictor(self) -> MLPredictor:
        return MLPredictor(self._store)
