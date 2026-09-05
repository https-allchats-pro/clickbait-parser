from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import train_test_split

from domain.ml import MLTrainingError, TrainingMetrics

# Positive class for clickbait binary classification.
LABEL_CLICKBAIT = 1
LABEL_NORMAL = 0


@dataclass(frozen=True)
class FittedPipeline:
    vectorizer: TfidfVectorizer
    classifier: LogisticRegression
    metrics: TrainingMetrics


def build_vectorizer() -> TfidfVectorizer:
    return TfidfVectorizer(
        lowercase=True,
        ngram_range=(1, 2),
        min_df=1,
        max_df=0.95,
    )


def build_classifier() -> LogisticRegression:
    return LogisticRegression(
        max_iter=1000,
        random_state=42,
    )


def train_tfidf_logreg(
    texts: list[str],
    labels: list[int],
    *,
    test_size: float = 0.2,
    random_state: int = 42,
) -> FittedPipeline:
    """Fit TF-IDF + LogisticRegression with a stratified hold-out split."""
    if len(texts) != len(labels):
        raise MLTrainingError("texts and labels length mismatch")
    if not texts:
        raise MLTrainingError(
            "Not enough labeled data for training.\n"
            "Need at least one CLICKBAIT and one NORMAL post."
        )

    n_clickbait = sum(1 for y in labels if y == LABEL_CLICKBAIT)
    n_normal = sum(1 for y in labels if y == LABEL_NORMAL)
    if n_clickbait < 1 or n_normal < 1:
        raise MLTrainingError(
            "Not enough labeled data for training.\n"
            "Need at least one CLICKBAIT and one NORMAL post."
        )

    # Stratified split needs ≥2 samples per class so both appear in train and test.
    if n_clickbait < 2 or n_normal < 2:
        raise MLTrainingError(
            "Dataset is too small for a stratified train/test split.\n"
            "Need at least 2 CLICKBAIT and 2 NORMAL labeled posts."
        )

    try:
        x_train, x_test, y_train, y_test = train_test_split(
            texts,
            labels,
            test_size=test_size,
            random_state=random_state,
            stratify=labels,
        )
    except ValueError as exc:
        raise MLTrainingError(
            "Cannot create a stratified train/test split with the current dataset.\n"
            f"Details: {exc}"
        ) from exc

    vectorizer = build_vectorizer()
    x_train_vec = vectorizer.fit_transform(x_train)
    x_test_vec = vectorizer.transform(x_test)

    classifier = build_classifier()
    classifier.fit(x_train_vec, y_train)

    y_pred = classifier.predict(x_test_vec)
    metrics = TrainingMetrics(
        accuracy=float(accuracy_score(y_test, y_pred)),
        precision=float(
            precision_score(y_test, y_pred, pos_label=LABEL_CLICKBAIT, zero_division=0.0)
        ),
        recall=float(
            recall_score(y_test, y_pred, pos_label=LABEL_CLICKBAIT, zero_division=0.0)
        ),
        f1=float(f1_score(y_test, y_pred, pos_label=LABEL_CLICKBAIT, zero_division=0.0)),
        train_samples=len(y_train),
        test_samples=len(y_test),
        clickbait_samples=n_clickbait,
        normal_samples=n_normal,
    )
    return FittedPipeline(
        vectorizer=vectorizer,
        classifier=classifier,
        metrics=metrics,
    )


def predict_proba_clickbait(
    *,
    vectorizer: Any,
    classifier: Any,
    text: str,
) -> float:
    """Return P(clickbait) for a single text."""
    matrix = vectorizer.transform([text or ""])
    proba = classifier.predict_proba(matrix)[0]
    classes = list(classifier.classes_)
    if LABEL_CLICKBAIT in classes:
        return float(proba[classes.index(LABEL_CLICKBAIT)])
    # Fallback if class encoding differs.
    return float(proba[-1])
