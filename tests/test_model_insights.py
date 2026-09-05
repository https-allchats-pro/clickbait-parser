from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from app.ml.feature_insights import (
    ModelFeature,
    ModelInsightsError,
    ModelInsightsService,
)
from app.ml.storage import ModelStore
from app.ml.trainer import LABEL_CLICKBAIT, LABEL_NORMAL, train_tfidf_logreg
from domain.ml import MLModelNotFoundError, ModelInfo


def _train_toy_bundle():
    texts = [
        "вы не поверите что произошло продолжение по ссылке",
        "узнайте подробнее шокирующая правда срочно",
        "сенсация вы не поверите шок",
        "продолжение по ссылке срочно узнайте",
        "обычный пост про погоду сегодня заявил",
        "новости района сообщил правительство",
        "спокойный текст о работе закон документ",
        "ежедневный отчёт по проекту заявил закон",
    ]
    labels = [
        LABEL_CLICKBAIT,
        LABEL_CLICKBAIT,
        LABEL_CLICKBAIT,
        LABEL_CLICKBAIT,
        LABEL_NORMAL,
        LABEL_NORMAL,
        LABEL_NORMAL,
        LABEL_NORMAL,
    ]
    return train_tfidf_logreg(texts, labels)


class ModelInsightsServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = ModelStore(Path(self._tmp.name) / "models")
        self.service = ModelInsightsService(self.store)

    def _save_trained(self, *, version: int = 1) -> ModelInfo:
        fitted = _train_toy_bundle()
        info = ModelInfo(
            version=version,
            trained_at=datetime(2026, 9, 4, 12, 42, tzinfo=UTC),
            metrics=fitted.metrics,
            label_count_at_train=(
                fitted.metrics.clickbait_samples + fitted.metrics.normal_samples
            ),
        )
        self.store.save(
            vectorizer=fitted.vectorizer,
            classifier=fitted.classifier,
            info=info,
        )
        return info

    def test_missing_model(self) -> None:
        self.assertFalse(self.service.is_ready())
        self.assertIsNone(self.service.get_model_info())
        with self.assertRaises(MLModelNotFoundError):
            self.service.list_feature_coefficients()

    def test_feature_names_match_coefficients(self) -> None:
        self._save_trained()
        features = self.service.list_feature_coefficients()
        self.assertGreater(len(features), 0)
        names = [f.term for f in features]
        self.assertEqual(len(names), len(set(names)))
        for feature in features:
            self.assertIsInstance(feature, ModelFeature)
            self.assertTrue(feature.term)
            self.assertIsInstance(feature.coefficient, float)

        # Reload from store — names must come from vectorizer
        bundle = self.store.load_bundle()
        expected = list(bundle["vectorizer"].get_feature_names_out())
        self.assertEqual(names, expected)
        self.assertEqual(len(features), len(expected))

    def test_top_clickbait_sorted_descending(self) -> None:
        self._save_trained()
        top = self.service.get_top_clickbait_features(limit=10)
        self.assertTrue(top)
        self.assertTrue(all(f.coefficient > 0 for f in top))
        coeffs = [f.coefficient for f in top]
        self.assertEqual(coeffs, sorted(coeffs, reverse=True))

    def test_top_normal_sorted_ascending(self) -> None:
        self._save_trained()
        top = self.service.get_top_normal_features(limit=10)
        self.assertTrue(top)
        self.assertTrue(all(f.coefficient < 0 for f in top))
        coeffs = [f.coefficient for f in top]
        self.assertEqual(coeffs, sorted(coeffs))  # most negative first

    def test_limit(self) -> None:
        self._save_trained()
        self.assertEqual(len(self.service.get_top_clickbait_features(limit=3)), 3)
        self.assertEqual(len(self.service.get_top_normal_features(limit=2)), 2)
        self.assertEqual(len(self.service.get_top_clickbait_features(limit=0)), 0)

    def test_malformed_bundle_missing_coef(self) -> None:
        self._save_trained()
        vectorizer = self.store.load_bundle()["vectorizer"]

        class _BadClf:
            pass

        with mock.patch.object(
            self.store,
            "load_bundle",
            return_value={"vectorizer": vectorizer, "classifier": _BadClf()},
        ):
            with self.assertRaises(ModelInsightsError):
                self.service.list_feature_coefficients()

    def test_length_mismatch(self) -> None:
        self._save_trained()
        import numpy as np

        vectorizer = self.store.load_bundle()["vectorizer"]

        class _BadClf:
            classes_ = np.array([LABEL_NORMAL, LABEL_CLICKBAIT])
            coef_ = np.array([[0.1, 0.2, 0.3]])

        with mock.patch.object(
            self.store,
            "load_bundle",
            return_value={"vectorizer": vectorizer, "classifier": _BadClf()},
        ):
            with self.assertRaises(ModelInsightsError):
                self.service.list_feature_coefficients()

    def test_model_info_from_store(self) -> None:
        saved = self._save_trained(version=3)
        info = self.service.get_model_info()
        assert info is not None
        self.assertEqual(info.version, 3)
        self.assertEqual(info.metrics.f1, saved.metrics.f1)


if __name__ == "__main__":
    unittest.main()
