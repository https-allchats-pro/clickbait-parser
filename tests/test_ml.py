from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from datetime import UTC, datetime
from pathlib import Path

from analysis.ml_analyzer import MLClickbaitAnalyzer
from analysis.models import ClickbaitAnalysis, ClickbaitFeatures
from app.ml.predictor import MLPredictor
from app.ml.service import MLTrainingService
from app.ml.storage import ModelStore
from app.ml.trainer import (
    LABEL_CLICKBAIT,
    LABEL_NORMAL,
    build_classifier,
    build_vectorizer,
    train_tfidf_logreg,
)
from domain.dataset import DatasetLabel, PostLabel
from domain.ml import MLModelNotFoundError, MLTrainingError
from domain.posts import SOURCE_VK_CATALOG, CatalogPost
from infrastructure.db.database import init_schema
from infrastructure.db.repositories.analysis_repository import AnalysisRepository
from infrastructure.db.repositories.label_repository import LabelRepository
from infrastructure.db.repositories.post_repository import PostRepository


def _post(owner: int, post_id: int, text: str) -> CatalogPost:
    return CatalogPost(
        source=SOURCE_VK_CATALOG,
        owner_id=owner,
        post_id=post_id,
        text=text,
        date=datetime.fromtimestamp(1_700_000_000, tz=UTC),
        views=999_999,
        likes=50_000,
        reposts=10_000,
        comments=1_000,
    )


class MLTrainerUnitTests(unittest.TestCase):
    def test_vectorizer_and_classifier_defaults(self) -> None:
        vec = build_vectorizer()
        self.assertEqual(vec.ngram_range, (1, 2))
        self.assertTrue(vec.lowercase)
        self.assertEqual(vec.min_df, 1)
        self.assertEqual(vec.max_df, 0.95)

        clf = build_classifier()
        self.assertEqual(clf.max_iter, 1000)
        self.assertEqual(clf.random_state, 42)

    def test_not_enough_data_message(self) -> None:
        with self.assertRaises(MLTrainingError) as ctx:
            train_tfidf_logreg(["only clickbait"], [LABEL_CLICKBAIT])
        self.assertIn("Not enough labeled data for training", str(ctx.exception))
        self.assertIn("Need at least one CLICKBAIT and one NORMAL", str(ctx.exception))

    def test_too_small_for_stratified_split(self) -> None:
        with self.assertRaises(MLTrainingError) as ctx:
            train_tfidf_logreg(
                ["clickbait text", "normal text"],
                [LABEL_CLICKBAIT, LABEL_NORMAL],
            )
        self.assertIn("too small for a stratified train/test split", str(ctx.exception))

    def test_train_predict_proba_and_metrics(self) -> None:
        texts = [
            "вы не поверите что произошло продолжение по ссылке",
            "узнайте подробнее шокирующая правда",
            "сенсация вы не поверите",
            "продолжение по ссылке срочно",
            "обычный пост про погоду сегодня",
            "новости района без кликбейта",
            "спокойный текст о работе",
            "ежедневный отчёт по проекту",
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
        fitted = train_tfidf_logreg(texts, labels)
        self.assertEqual(fitted.metrics.clickbait_samples, 4)
        self.assertEqual(fitted.metrics.normal_samples, 4)
        self.assertEqual(
            fitted.metrics.train_samples + fitted.metrics.test_samples, 8
        )
        self.assertGreater(fitted.metrics.test_samples, 0)
        proba = fitted.classifier.predict_proba(
            fitted.vectorizer.transform(["вы не поверите продолжение"])
        )[0]
        self.assertEqual(len(proba), 2)
        self.assertAlmostEqual(float(sum(proba)), 1.0, places=5)


class MLServiceIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        db_path = root / "t.db"
        self.models_dir = root / "models"
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        init_schema(self.conn)
        self.posts = PostRepository(self.conn)
        self.labels = LabelRepository(self.conn)
        self.analyses = AnalysisRepository(self.conn)
        self.store = ModelStore(self.models_dir)
        self.service = MLTrainingService(
            posts=self.posts,
            labels=self.labels,
            store=self.store,
        )
        self._now = int(time.time())

    def tearDown(self) -> None:
        self.conn.close()

    def _add_labeled(
        self,
        *,
        owner: int,
        text: str,
        human: DatasetLabel,
        rule_clickbait: bool = False,
    ) -> int:
        local_id = self.posts.upsert(_post(owner, owner, text))
        self.labels.save(
            PostLabel(
                post_id=local_id,
                label=human,
                created_at=self._now,
                updated_at=self._now,
            )
        )
        # Deliberately mismatch rule analysis vs human label (leakage check).
        self.analyses.save(
            ClickbaitAnalysis(
                post_id=local_id,
                score=0.9 if rule_clickbait else 0.1,
                is_clickbait=rule_clickbait,
                reasons=["rule"],
                features=ClickbaitFeatures(),
            )
        )
        return local_id

    def _seed_binary(self, n_each: int = 4) -> None:
        for i in range(n_each):
            self._add_labeled(
                owner=100 + i,
                text=f"вы не поверите кликбейт номер {i} продолжение по ссылке",
                human=DatasetLabel.CLICKBAIT,
                rule_clickbait=False,  # human CLICKBAIT, rule says normal
            )
            self._add_labeled(
                owner=200 + i,
                text=f"спокойный обычный пост номер {i} про дела",
                human=DatasetLabel.NORMAL,
                rule_clickbait=True,  # human NORMAL, rule says clickbait
            )

    def test_borderline_excluded_from_training_pairs(self) -> None:
        self._seed_binary(2)
        self._add_labeled(
            owner=300,
            text="спорный пост borderline",
            human=DatasetLabel.BORDERLINE,
        )
        texts, y = self.service.load_training_pairs()
        self.assertEqual(len(texts), 4)
        self.assertEqual(sum(1 for v in y if v == LABEL_CLICKBAIT), 2)
        self.assertEqual(sum(1 for v in y if v == LABEL_NORMAL), 2)
        self.assertTrue(all(v in (LABEL_CLICKBAIT, LABEL_NORMAL) for v in y))

    def test_target_from_human_labels_not_post_analysis(self) -> None:
        """Leakage guard: y must follow post_labels, not post_analysis.is_clickbait."""
        self._seed_binary(2)
        _texts, y = self.service.load_training_pairs()
        human_rows = [
            row
            for row in self.labels.list_all()
            if row.label in (DatasetLabel.CLICKBAIT, DatasetLabel.NORMAL)
        ]
        self.assertEqual(len(y), len(human_rows))
        for label_row, cls in zip(human_rows, y, strict=True):
            analysis = self.analyses.get_by_post_id(label_row.post_id)
            assert analysis is not None
            rule_cls = LABEL_CLICKBAIT if analysis.is_clickbait else LABEL_NORMAL
            human_cls = (
                LABEL_CLICKBAIT
                if label_row.label == DatasetLabel.CLICKBAIT
                else LABEL_NORMAL
            )
            self.assertEqual(cls, human_cls)
            self.assertNotEqual(cls, rule_cls)

    def test_train_save_load_version_bump(self) -> None:
        self._seed_binary(4)
        r1 = self.service.train()
        self.assertEqual(r1.info.version, 1)
        self.assertTrue(self.store.exists())
        self.assertTrue(self.store.meta_path.is_file())

        loaded = self.store.load_info()
        assert loaded is not None
        self.assertEqual(loaded.version, 1)
        self.assertGreaterEqual(loaded.metrics.train_samples, 1)
        self.assertGreaterEqual(loaded.metrics.test_samples, 1)

        predictor = MLPredictor(self.store)
        proba = predictor.predict_proba_clickbait("вы не поверите продолжение по ссылке")
        self.assertGreaterEqual(proba, 0.0)
        self.assertLessEqual(proba, 1.0)

        r2 = self.service.train()
        self.assertEqual(r2.info.version, 2)
        self.assertEqual(self.store.load_info().version, 2)  # type: ignore[union-attr]

    def test_new_labels_since_train_does_not_auto_retrain(self) -> None:
        self._seed_binary(4)
        self.service.train()
        version_before = self.store.current_version()
        self._add_labeled(
            owner=400,
            text="новый кликбейт после train",
            human=DatasetLabel.CLICKBAIT,
        )
        self.assertEqual(self.service.new_labels_since_train(), 1)
        self.assertEqual(self.store.current_version(), version_before)

    def test_predictor_without_model(self) -> None:
        predictor = MLPredictor(self.store)
        self.assertFalse(predictor.is_ready())
        with self.assertRaises(MLModelNotFoundError):
            predictor.predict_proba_clickbait("anything")

    def test_ml_analyzer_predicts_catalog_post(self) -> None:
        self._seed_binary(4)
        self.service.train()
        analyzer = MLClickbaitAnalyzer(store=self.store)
        post = _post(999, 1, "вы не поверите что произошло")
        post.id = 1
        result = analyzer.analyze(post)
        self.assertIsInstance(result, ClickbaitAnalysis)
        self.assertGreaterEqual(result.score, 0.0)
        self.assertLessEqual(result.score, 1.0)
        self.assertIn("ml_tfidf_logreg", result.reasons)

    def test_ml_analyzer_missing_model(self) -> None:
        analyzer = MLClickbaitAnalyzer(store=self.store)
        post = _post(1, 1, "text")
        post.id = 1
        with self.assertRaises(MLModelNotFoundError):
            analyzer.analyze(post)

    def test_not_enough_labels_via_service(self) -> None:
        self._add_labeled(
            owner=1,
            text="only one clickbait",
            human=DatasetLabel.CLICKBAIT,
        )
        with self.assertRaises(MLTrainingError) as ctx:
            self.service.train()
        self.assertIn("Not enough labeled data for training", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
