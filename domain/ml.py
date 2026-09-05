from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


class MLTrainingError(ValueError):
    """User-facing ML training / dataset error."""


class MLModelNotFoundError(RuntimeError):
    """Saved model artifact is missing."""


@dataclass(frozen=True)
class TrainingMetrics:
    accuracy: float
    precision: float
    recall: float
    f1: float
    train_samples: int
    test_samples: int
    clickbait_samples: int
    normal_samples: int


@dataclass(frozen=True)
class ModelInfo:
    version: int
    trained_at: datetime
    metrics: TrainingMetrics
    label_count_at_train: int
    algorithm: str = "tfidf_logreg"


@dataclass(frozen=True)
class TrainingResult:
    info: ModelInfo
    model_path: str
