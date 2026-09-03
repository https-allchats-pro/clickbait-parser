from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from analysis.analyzer import RuleBasedClickbaitAnalyzer
from analysis.models import ClickbaitAnalysis, ClickbaitFeatures
from domain.posts import CatalogPost, PostLink, SOURCE_VK_CATALOG
from infrastructure.db.database import init_schema
from infrastructure.db.repositories.analysis_repository import AnalysisRepository
from infrastructure.db.repositories.post_repository import PostRepository


def _post(
    text: str,
    *,
    links: list[str] | None = None,
    local_id: int = 1,
) -> CatalogPost:
    return CatalogPost(
        id=local_id,
        source=SOURCE_VK_CATALOG,
        owner_id=-1,
        post_id=100,
        text=text,
        date=datetime.fromtimestamp(1_700_000_000, tz=UTC),
        links=[PostLink(url=url, position=i) for i, url in enumerate(links or [])],
    )


class AnalyzerRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analyzer = RuleBasedClickbaitAnalyzer(threshold=0.5)

    def test_continuation_bait(self) -> None:
        result = self.analyzer.analyze(_post("Продолжение читайте по ссылке"))
        self.assertIn("continuation_bait", result.reasons)
        self.assertTrue(result.features.has_continuation_phrase)

    def test_curiosity_bait(self) -> None:
        result = self.analyzer.analyze(
            _post("Вы не поверите, что произошло дальше...")
        )
        self.assertIn("curiosity_bait", result.reasons)
        self.assertTrue(result.features.has_curiosity_phrase)
        self.assertTrue(result.features.has_ellipsis)

    def test_cta_near_link(self) -> None:
        result = self.analyzer.analyze(
            _post(
                "Полную историю читайте здесь:\nhttps://example.com/article",
                links=["https://example.com/article"],
            )
        )
        self.assertIn("cta_near_link", result.reasons)
        self.assertIn("external_link", result.reasons)
        self.assertTrue(result.features.link_near_cta)
        self.assertGreaterEqual(result.score, 0.5)
        self.assertTrue(result.is_clickbait)

    def test_normal_informational_post_with_link(self) -> None:
        result = self.analyzer.analyze(
            _post(
                "Сегодня в городе открыли новый мост через реку. "
                "Строительство заняло три года. Подробности на сайте администрации: "
                "https://city.example/news/bridge",
                links=["https://city.example/news/bridge"],
            )
        )
        self.assertIn("external_link", result.reasons)
        # "подробности" is a weak CTA — still should not alone tip a long info post
        # over threshold without continuation/curiosity bait.
        self.assertFalse(result.is_clickbait)
        self.assertLess(result.score, 0.5)

    def test_score_clamped(self) -> None:
        result = self.analyzer.analyze(
            _post(
                "ВЫ НЕ ПОВЕРИТЕ!!! Что произошло дальше... "
                "Продолжение читайте по ссылке https://example.com/x "
                "😱😱😱",
                links=["https://example.com/x"],
            )
        )
        self.assertGreaterEqual(result.score, 0.0)
        self.assertLessEqual(result.score, 1.0)

    def test_threshold_configurable(self) -> None:
        post = _post(
            "Читайте подробнее https://example.com",
            links=["https://example.com"],
        )
        low = RuleBasedClickbaitAnalyzer(threshold=0.9).analyze(post)
        high_sens = RuleBasedClickbaitAnalyzer(threshold=0.1).analyze(post)
        self.assertEqual(low.score, high_sens.score)
        self.assertFalse(low.is_clickbait)
        self.assertTrue(high_sens.is_clickbait)

    def test_requires_local_id(self) -> None:
        post = _post("текст")
        post.id = None
        with self.assertRaises(ValueError):
            self.analyzer.analyze(post)


class AnalysisRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        path = Path(self._tmp.name) / "t.db"
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        init_schema(self.conn)
        self.posts = PostRepository(self.conn)
        self.repo = AnalysisRepository(self.conn)
        self.post_id = self.posts.upsert(
            CatalogPost(
                source=SOURCE_VK_CATALOG,
                owner_id=-10,
                post_id=55,
                text="hello",
                date=datetime.fromtimestamp(1_700_000_000, tz=UTC),
                links=[PostLink(url="https://example.com", position=0)],
            )
        )

    def tearDown(self) -> None:
        self.conn.close()

    def test_save_get_and_upsert(self) -> None:
        analysis = ClickbaitAnalysis(
            post_id=self.post_id,
            score=0.8,
            is_clickbait=True,
            reasons=["continuation_bait", "external_link"],
            features=ClickbaitFeatures(
                has_continuation_phrase=True,
                has_external_link=True,
            ),
        )
        self.repo.save(analysis)
        got = self.repo.get_by_post_id(self.post_id)
        assert got is not None
        self.assertEqual(got.score, 0.8)
        self.assertTrue(got.is_clickbait)
        self.assertEqual(got.reasons, ["continuation_bait", "external_link"])
        self.assertTrue(got.features.has_continuation_phrase)

        analysis.score = 0.2
        analysis.is_clickbait = False
        analysis.reasons = ["external_link"]
        self.repo.save(analysis)
        got2 = self.repo.get_by_post_id(self.post_id)
        assert got2 is not None
        self.assertEqual(got2.score, 0.2)
        self.assertFalse(got2.is_clickbait)
        count = self.conn.execute("SELECT COUNT(*) AS c FROM post_analysis").fetchone()["c"]
        self.assertEqual(count, 1)

    def test_get_clickbait(self) -> None:
        self.repo.save(
            ClickbaitAnalysis(
                post_id=self.post_id,
                score=0.9,
                is_clickbait=True,
                reasons=["curiosity_bait"],
                features=ClickbaitFeatures(has_curiosity_phrase=True),
            )
        )
        rows = self.repo.get_clickbait(limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].post_id, self.post_id)


if __name__ == "__main__":
    unittest.main()
