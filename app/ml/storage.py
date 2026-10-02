from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib

from domain.ml import MLModelNotFoundError, ModelInfo, TrainingMetrics

MODEL_FILENAME = "clickbait_model.joblib"
META_FILENAME = "clickbait_model.meta.json"


def default_models_dir() -> Path:
    """Project-local ``models/`` (or bundled path when frozen)."""
    from app.runtime_paths import default_models_dir as _default_models_dir

    return _default_models_dir()


class ModelStore:
    """Persist / load the current TF-IDF + LogisticRegression artifact."""

    def __init__(self, models_dir: Path | str | None = None) -> None:
        self._dir = Path(models_dir) if models_dir is not None else default_models_dir()
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def model_path(self) -> Path:
        return self._dir / MODEL_FILENAME

    @property
    def meta_path(self) -> Path:
        return self._dir / META_FILENAME

    def exists(self) -> bool:
        return self.model_path.is_file()

    def current_version(self) -> int:
        info = self.load_info()
        return 0 if info is None else int(info.version)

    def next_version(self) -> int:
        return self.current_version() + 1

    def save(
        self,
        *,
        vectorizer: Any,
        classifier: Any,
        info: ModelInfo,
    ) -> Path:
        payload = {
            "vectorizer": vectorizer,
            "classifier": classifier,
            "metadata": self._info_to_dict(info),
        }
        joblib.dump(payload, self.model_path)
        self.meta_path.write_text(
            json.dumps(self._info_to_dict(info), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return self.model_path

    def load_bundle(self) -> dict[str, Any]:
        if not self.exists():
            raise MLModelNotFoundError("Model is not trained yet.")
        payload = joblib.load(self.model_path)
        if not isinstance(payload, dict):
            raise MLModelNotFoundError("Invalid model artifact.")
        if "vectorizer" not in payload or "classifier" not in payload:
            raise MLModelNotFoundError("Model artifact is missing vectorizer/classifier.")
        return payload

    def load_info(self) -> ModelInfo | None:
        if self.meta_path.is_file():
            raw = json.loads(self.meta_path.read_text(encoding="utf-8"))
            return self._info_from_dict(raw)
        if not self.exists():
            return None
        payload = joblib.load(self.model_path)
        meta = payload.get("metadata") if isinstance(payload, dict) else None
        if not isinstance(meta, dict):
            return None
        return self._info_from_dict(meta)

    @staticmethod
    def _info_to_dict(info: ModelInfo) -> dict[str, Any]:
        m = info.metrics
        return {
            "version": info.version,
            "trained_at": info.trained_at.astimezone(UTC).isoformat(),
            "algorithm": info.algorithm,
            "label_count_at_train": info.label_count_at_train,
            "train_samples": m.train_samples,
            "test_samples": m.test_samples,
            "clickbait_samples": m.clickbait_samples,
            "normal_samples": m.normal_samples,
            "accuracy": m.accuracy,
            "precision": m.precision,
            "recall": m.recall,
            "f1": m.f1,
        }

    @staticmethod
    def _info_from_dict(raw: dict[str, Any]) -> ModelInfo:
        trained_raw = str(raw.get("trained_at") or "")
        try:
            trained_at = datetime.fromisoformat(trained_raw)
        except ValueError:
            trained_at = datetime.now(tz=UTC)
        if trained_at.tzinfo is None:
            trained_at = trained_at.replace(tzinfo=UTC)
        metrics = TrainingMetrics(
            accuracy=float(raw.get("accuracy") or 0.0),
            precision=float(raw.get("precision") or 0.0),
            recall=float(raw.get("recall") or 0.0),
            f1=float(raw.get("f1") or 0.0),
            train_samples=int(raw.get("train_samples") or 0),
            test_samples=int(raw.get("test_samples") or 0),
            clickbait_samples=int(raw.get("clickbait_samples") or 0),
            normal_samples=int(raw.get("normal_samples") or 0),
        )
        return ModelInfo(
            version=int(raw.get("version") or 1),
            trained_at=trained_at,
            metrics=metrics,
            label_count_at_train=int(raw.get("label_count_at_train") or 0),
            algorithm=str(raw.get("algorithm") or "tfidf_logreg"),
        )
