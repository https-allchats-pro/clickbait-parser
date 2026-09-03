from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from analysis.models import ClickbaitAnalysis, ClickbaitFeatures
from app.dataset.service import DatasetService
from domain.dataset import DatasetLabel
from domain.posts import SOURCE_VK_CATALOG, CatalogPost, PostLink
from infrastructure.db.database import init_schema
from infrastructure.db.repositories.analysis_repository import AnalysisRepository
from infrastructure.db.repositories.label_repository import LabelRepository
from infrastructure.db.repositories.post_repository import PostRepository


class LabelRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        path = Path(self._tmp.name) / "t.db"
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        init_schema(self.conn)
        self.posts = PostRepository(self.conn)
        self.labels = LabelRepository(self.conn)
        self.post_id = self.posts.upsert(
            CatalogPost(
                source=SOURCE_VK_CATALOG,
                owner_id=-1,
                post_id=10,
                text="hello",
                date=datetime.fromtimestamp(1_700_000_000, tz=UTC),
            )
        )

    def tearDown(self) -> None:
        self.conn.close()

    def test_insert_get_upsert(self) -> None:
        from domain.dataset import PostLabel
        import time

        now = int(time.time())
        saved = self.labels.save(
            PostLabel(
                post_id=self.post_id,
                label=DatasetLabel.CLICKBAIT,
                created_at=now,
                updated_at=now,
            )
        )
        got = self.labels.get_by_post_id(self.post_id)
        assert got is not None
        self.assertEqual(got.label, DatasetLabel.CLICKBAIT)
        self.assertEqual(saved.id, got.id)

        self.labels.save(
            PostLabel(
                post_id=self.post_id,
                label=DatasetLabel.NORMAL,
                created_at=now,
                updated_at=now,
                note="changed mind",
            )
        )
        got2 = self.labels.get_by_post_id(self.post_id)
        assert got2 is not None
        self.assertEqual(got2.label, DatasetLabel.NORMAL)
        self.assertEqual(got2.note, "changed mind")
        self.assertEqual(self.labels.count_labeled(), 1)

    def test_list_and_count(self) -> None:
        from domain.dataset import PostLabel
        import time

        second = self.posts.upsert(
            CatalogPost(
                source=SOURCE_VK_CATALOG,
                owner_id=-2,
                post_id=11,
                text="other",
                date=datetime.fromtimestamp(1_700_000_100, tz=UTC),
            )
        )
        now = int(time.time())
        self.labels.save(
            PostLabel(post_id=self.post_id, label=DatasetLabel.CLICKBAIT, created_at=now, updated_at=now)
        )
        self.labels.save(
            PostLabel(post_id=second, label=DatasetLabel.BORDERLINE, created_at=now, updated_at=now)
        )
        counts = self.labels.count_by_label()
        self.assertEqual(counts[DatasetLabel.CLICKBAIT], 1)
        self.assertEqual(counts[DatasetLabel.BORDERLINE], 1)
        self.assertEqual(len(self.labels.list_by_label(DatasetLabel.CLICKBAIT)), 1)

    def test_cascade_delete(self) -> None:
        from domain.dataset import PostLabel
        import time

        now = int(time.time())
        self.labels.save(
            PostLabel(post_id=self.post_id, label=DatasetLabel.NORMAL, created_at=now, updated_at=now)
        )
        self.posts.delete(SOURCE_VK_CATALOG, -1, 10)
        self.assertIsNone(self.labels.get_by_post_id(self.post_id))


class DatasetServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        path = Path(self._tmp.name) / "t.db"
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        init_schema(self.conn)
        self.posts = PostRepository(self.conn)
        self.labels = LabelRepository(self.conn)
        self.analyses = AnalysisRepository(self.conn)
        self.service = DatasetService(
            posts=self.posts,
            labels=self.labels,
            analyses=self.analyses,
        )
        self.p1 = self.posts.upsert(
            CatalogPost(
                source=SOURCE_VK_CATALOG,
                owner_id=-10,
                post_id=1,
                text="Продолжение читайте по ссылке https://example.com",
                date=datetime.fromtimestamp(1_700_000_000, tz=UTC),
                links=[PostLink(url="https://example.com", position=0)],
            )
        )
        self.p2 = self.posts.upsert(
            CatalogPost(
                source=SOURCE_VK_CATALOG,
                owner_id=-20,
                post_id=2,
                text="Обычная новость без кликбейта",
                date=datetime.fromtimestamp(1_700_000_050, tz=UTC),
            )
        )
        self.analyses.save(
            ClickbaitAnalysis(
                post_id=self.p1,
                score=0.8,
                is_clickbait=True,
                reasons=["continuation_bait", "external_link"],
                features=ClickbaitFeatures(
                    has_continuation_phrase=True,
                    has_external_link=True,
                ),
            )
        )
        self.analyses.save(
            ClickbaitAnalysis(
                post_id=self.p2,
                score=0.0,
                is_clickbait=False,
                reasons=[],
                features=ClickbaitFeatures(),
            )
        )

    def tearDown(self) -> None:
        self.conn.close()

    def test_label_and_error(self) -> None:
        saved = self.service.label_post(self.p1, DatasetLabel.CLICKBAIT)
        self.assertEqual(saved.label, DatasetLabel.CLICKBAIT)
        with self.assertRaises(ValueError):
            self.service.label_post(99999, DatasetLabel.NORMAL)

    def test_next_unlabeled_modes(self) -> None:
        first = self.service.get_next_unlabeled_post(mode="default")
        assert first is not None
        self.assertEqual(first.id, self.p1)
        self.service.label_post(self.p1, DatasetLabel.NORMAL)
        second = self.service.get_next_unlabeled_post(mode="default")
        assert second is not None
        self.assertEqual(second.id, self.p2)

        # suspicious prefers high score among unlabeled
        self.service.label_post(self.p2, DatasetLabel.NORMAL)
        # create a third unlabeled with high score
        p3 = self.posts.upsert(
            CatalogPost(
                source=SOURCE_VK_CATALOG,
                owner_id=-30,
                post_id=3,
                text="x",
                date=datetime.fromtimestamp(1_700_000_200, tz=UTC),
            )
        )
        self.analyses.save(
            ClickbaitAnalysis(
                post_id=p3,
                score=0.95,
                is_clickbait=True,
                reasons=["curiosity_bait"],
                features=ClickbaitFeatures(has_curiosity_phrase=True),
            )
        )
        # unlabel p1 for suspicious pick
        self.conn.execute("DELETE FROM post_labels WHERE post_id = ?", (self.p1,))
        self.conn.commit()
        sus = self.service.get_next_unlabeled_post(mode="suspicious")
        assert sus is not None
        self.assertIn(sus.id, {self.p1, p3})
        # p3 has higher score
        self.assertEqual(sus.id, p3)

    def test_stats_and_disagreement(self) -> None:
        self.service.label_post(self.p1, DatasetLabel.NORMAL)  # human normal, rule clickbait
        self.service.label_post(self.p2, DatasetLabel.CLICKBAIT)  # human clickbait, rule normal
        stats = self.service.get_dataset_stats()
        self.assertEqual(stats.total_labeled, 2)
        self.assertEqual(stats.unlabeled, 0)
        self.assertEqual(stats.disagreement_human_normal_rule_clickbait, 1)
        self.assertEqual(stats.disagreement_human_clickbait_rule_normal, 1)

    def test_export_csv(self) -> None:
        self.service.label_post(self.p1, DatasetLabel.CLICKBAIT)
        out = Path(self._tmp.name) / "out.csv"
        path = self.service.export_csv(out)
        self.assertTrue(path.is_file())
        with path.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["label"], "clickbait")
        self.assertEqual(rows[0]["rule_prediction"], "clickbait")
        self.assertIn("continuation_bait", rows[0]["reasons"])
        self.assertIn("has_continuation_phrase", rows[0]["features"])
        self.assertEqual(rows[0]["post_id_vk"], "1")

    def test_validate_warnings(self) -> None:
        result = self.service.validate()
        self.assertTrue(any("No labeled" in w for w in result.warnings))
        self.service.label_post(self.p1, DatasetLabel.CLICKBAIT)
        result2 = self.service.validate()
        self.assertTrue(any("clickbait examples" in w for w in result2.warnings))


if __name__ == "__main__":
    unittest.main()
