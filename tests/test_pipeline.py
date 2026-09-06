from __future__ import annotations

import unittest
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

from analysis.models import ClickbaitAnalysis, ClickbaitFeatures
from app.pipeline.service import ClickbaitPipeline
from domain.pipeline import (
    PipelineProgress,
    PipelineRequest,
    PipelineResult,
    PipelineState,
)
from domain.posts import CatalogPost, CollectResult, SOURCE_VK_CATALOG, UpsertResult


def _post(
    post_id: int,
    *,
    local_id: int | None = None,
    text: str = "hello",
    views: int = 0,
) -> CatalogPost:
    return CatalogPost(
        source=SOURCE_VK_CATALOG,
        owner_id=-100,
        post_id=post_id,
        text=text,
        date=datetime.fromtimestamp(1_700_000_000, tz=UTC),
        views=views,
        id=local_id if local_id is not None else post_id,
    )


def _analysis(post_id: int, *, score: float = 0.1) -> ClickbaitAnalysis:
    return ClickbaitAnalysis(
        post_id=post_id,
        score=score,
        is_clickbait=score >= 0.5,
        reasons=["external_link"] if score >= 0.5 else [],
        features=ClickbaitFeatures(has_external_link=True),
    )


class PipelineRequestTests(unittest.TestCase):
    def test_valid_limit(self) -> None:
        req = PipelineRequest(limit=10)
        self.assertEqual(req.limit, 10)
        self.assertIsNone(req.query)

    def test_zero_limit_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PipelineRequest(limit=0)

    def test_negative_limit_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PipelineRequest(limit=-1)

    def test_empty_query_becomes_none(self) -> None:
        req = PipelineRequest(limit=1, query="")
        self.assertIsNone(req.query)

    def test_whitespace_query_becomes_none(self) -> None:
        req = PipelineRequest(limit=1, query="   ")
        self.assertIsNone(req.query)

    def test_query_trimmed(self) -> None:
        req = PipelineRequest(limit=1, query="  новости  ")
        self.assertEqual(req.query, "новости")


class FakeCatalog:
    def __init__(
        self,
        posts: list[CatalogPost] | None = None,
        *,
        error: Exception | None = None,
        next_from: str | None = "cursor-1",
    ) -> None:
        self.posts = posts or []
        self.error = error
        self.next_from = next_from
        self.calls: list[dict[str, Any]] = []

    def collect(
        self,
        *,
        count: int = 100,
        start_from: str | None = None,
        pages: int = 1,
        page_size: int = 100,
        query: str | None = None,
        exclude_texts: frozenset[str] | set[str] | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        on_progress=None,
    ) -> CollectResult:
        self.calls.append(
            {
                "count": count,
                "start_from": start_from,
                "pages": pages,
                "page_size": page_size,
                "query": query,
                "exclude_texts": frozenset(exclude_texts or ()),
                "start_time": start_time,
                "end_time": end_time,
            }
        )
        if self.error is not None:
            raise self.error
        selected = self.posts[:count]
        if on_progress is not None:
            on_progress(len(selected), count)
        return CollectResult(
            fetched=len(selected),
            upsert=UpsertResult(inserted=len(selected)),
            posts=list(selected),
            next_from=self.next_from,
        )


class FakeAnalyzer:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[CatalogPost] = []

    def analyze(self, post: CatalogPost) -> ClickbaitAnalysis:
        self.calls.append(post)
        if self.error is not None:
            raise self.error
        assert post.id is not None
        return _analysis(post.id, score=0.2)


class FakeAnalysisRepo:
    def __init__(self) -> None:
        self.saved: list[ClickbaitAnalysis] = []

    def save_many(self, analyses: list[ClickbaitAnalysis]) -> None:
        self.saved.extend(analyses)


class ClickbaitPipelineTests(unittest.TestCase):
    def test_initial_state_idle(self) -> None:
        pipeline = ClickbaitPipeline(
            catalog_service=FakeCatalog(),
            analyzer=FakeAnalyzer(),
        )
        self.assertEqual(pipeline.state, PipelineState.IDLE)

    def test_happy_path_states_and_result(self) -> None:
        posts = [_post(1), _post(2)]
        catalog = FakeCatalog(posts)
        analyzer = FakeAnalyzer()
        analyses = FakeAnalysisRepo()
        events: list[PipelineProgress] = []

        pipeline = ClickbaitPipeline(
            catalog_service=catalog,
            analyzer=analyzer,
            analysis_repository=analyses,
            on_progress=events.append,
        )
        result = pipeline.run(PipelineRequest(limit=10))

        self.assertEqual(pipeline.state, PipelineState.COMPLETED)
        self.assertIsInstance(result, PipelineResult)
        self.assertEqual(result.collected, 2)
        self.assertEqual(result.analyzed, 2)
        self.assertEqual(len(result.posts), 2)
        self.assertEqual(len(analyses.saved), 2)

        states = [e.state for e in events]
        self.assertEqual(states[0], PipelineState.COLLECTING)
        self.assertIn(PipelineState.ANALYZING, states)
        self.assertEqual(states[-1], PipelineState.COMPLETED)

    def test_empty_result_completes(self) -> None:
        pipeline = ClickbaitPipeline(
            catalog_service=FakeCatalog([]),
            analyzer=FakeAnalyzer(),
            analysis_repository=FakeAnalysisRepo(),
        )
        result = pipeline.run(PipelineRequest(limit=5))
        self.assertEqual(pipeline.state, PipelineState.COMPLETED)
        self.assertEqual(result.posts, [])
        self.assertEqual(result.collected, 0)
        self.assertEqual(result.analyzed, 0)

    def test_limit_caps_result(self) -> None:
        posts = [_post(i) for i in range(10)]
        catalog = FakeCatalog(posts)
        pipeline = ClickbaitPipeline(
            catalog_service=catalog,
            analyzer=FakeAnalyzer(),
        )
        result = pipeline.run(PipelineRequest(limit=3))
        self.assertEqual(result.collected, 3)
        self.assertEqual(result.analyzed, 3)
        self.assertEqual(len(result.posts), 3)
        self.assertEqual(catalog.calls[0]["count"], 3)

    def test_query_passed_to_catalog(self) -> None:
        catalog = FakeCatalog([_post(1)])
        pipeline = ClickbaitPipeline(catalog_service=catalog, analyzer=FakeAnalyzer())
        pipeline.run(PipelineRequest(limit=1, query="новости"))
        self.assertEqual(catalog.calls[0]["query"], "новости")

    def test_requests_enough_pages_for_vk_sized_batches(self) -> None:
        catalog = FakeCatalog([_post(i) for i in range(100)])
        pipeline = ClickbaitPipeline(
            catalog_service=catalog,
            analyzer=FakeAnalyzer(),
            page_size=100,
        )
        pipeline.run(PipelineRequest(limit=100))
        self.assertGreaterEqual(catalog.calls[0]["pages"], 100)
        self.assertEqual(catalog.calls[0]["count"], 100)

    def test_none_query_passed(self) -> None:
        catalog = FakeCatalog([])
        pipeline = ClickbaitPipeline(catalog_service=catalog, analyzer=FakeAnalyzer())
        pipeline.run(PipelineRequest(limit=1, query=None))
        self.assertIsNone(catalog.calls[0]["query"])

    def test_collector_exception_sets_failed(self) -> None:
        catalog = FakeCatalog(error=RuntimeError("vk down"))
        pipeline = ClickbaitPipeline(catalog_service=catalog, analyzer=FakeAnalyzer())
        with self.assertRaises(RuntimeError):
            pipeline.run(PipelineRequest(limit=1))
        self.assertEqual(pipeline.state, PipelineState.FAILED)

    def test_analyzer_exception_sets_failed(self) -> None:
        catalog = FakeCatalog([_post(1)])
        analyzer = FakeAnalyzer(error=RuntimeError("boom"))
        pipeline = ClickbaitPipeline(catalog_service=catalog, analyzer=analyzer)
        with self.assertRaises(RuntimeError):
            pipeline.run(PipelineRequest(limit=1))
        self.assertEqual(pipeline.state, PipelineState.FAILED)

    def test_progress_callback_sequence(self) -> None:
        posts = [_post(1), _post(2), _post(3)]
        events: list[PipelineProgress] = []
        pipeline = ClickbaitPipeline(
            catalog_service=FakeCatalog(posts),
            analyzer=FakeAnalyzer(),
            on_progress=events.append,
        )
        pipeline.run(PipelineRequest(limit=3))

        collecting = [e for e in events if e.state == PipelineState.COLLECTING]
        analyzing = [e for e in events if e.state == PipelineState.ANALYZING]
        completed = [e for e in events if e.state == PipelineState.COMPLETED]

        self.assertGreaterEqual(len(collecting), 1)
        self.assertEqual(collecting[0].current, 0)
        self.assertEqual(collecting[0].total, 3)
        self.assertEqual(collecting[-1].current, 3)

        self.assertEqual(analyzing[0].current, 0)
        self.assertEqual(analyzing[0].total, 3)
        self.assertEqual(
            [(e.current, e.total) for e in analyzing if e.current > 0],
            [(1, 3), (2, 3), (3, 3)],
        )
        self.assertEqual(completed[-1].current, 3)
        self.assertEqual(completed[-1].total, 3)

    def test_uses_protocol_analyzer_not_concrete(self) -> None:
        analyzer = MagicMock()
        analyzer.analyze.side_effect = lambda post: _analysis(post.id or 0, score=0.9)
        catalog = FakeCatalog([_post(7, local_id=70)])
        pipeline = ClickbaitPipeline(catalog_service=catalog, analyzer=analyzer)
        result = pipeline.run(PipelineRequest(limit=1))
        analyzer.analyze.assert_called_once()
        self.assertTrue(result.posts[0].analysis.is_clickbait)

    def test_time_window_passed_to_catalog(self) -> None:
        catalog = FakeCatalog([_post(1)], next_from=None)
        pipeline = ClickbaitPipeline(catalog_service=catalog, analyzer=FakeAnalyzer())
        pipeline.run(
            PipelineRequest(limit=1, start_time=1_700_000_000, end_time=1_700_086_400)
        )
        self.assertEqual(catalog.calls[0]["start_time"], 1_700_000_000)
        self.assertEqual(catalog.calls[0]["end_time"], 1_700_086_400)

    def test_start_from_and_exclude_texts_passed(self) -> None:
        catalog = FakeCatalog([_post(1)], next_from="next-2")
        pipeline = ClickbaitPipeline(catalog_service=catalog, analyzer=FakeAnalyzer())
        result = pipeline.run(
            PipelineRequest(
                limit=1,
                start_from="cursor-a",
                exclude_texts=frozenset({"hello"}),
            )
        )
        self.assertEqual(catalog.calls[0]["start_from"], "cursor-a")
        self.assertEqual(catalog.calls[0]["exclude_texts"], frozenset({"hello"}))
        self.assertEqual(result.next_from, "next-2")

    def test_min_views_keeps_scanning_batches(self) -> None:
        pages = [
            [_post(1, text="a", views=10), _post(2, text="b", views=20)],
            [_post(3, text="c", views=5_000), _post(4, text="d", views=10)],
            [_post(5, text="e", views=9_000)],
        ]
        catalog = PagingFakeCatalog(pages)
        pipeline = ClickbaitPipeline(
            catalog_service=catalog,
            analyzer=FakeAnalyzer(),
            page_size=2,
        )
        with unittest.mock.patch.object(
            ClickbaitPipeline, "_min_views_delay", return_value=0
        ):
            result = pipeline.run(PipelineRequest(limit=2, min_views=1_000))
        self.assertEqual(len(result.posts), 2)
        self.assertEqual([p.post.post_id for p in result.posts], [3, 5])
        self.assertGreaterEqual(len(catalog.calls), 2)
        self.assertEqual(result.collected, 5)

    def test_min_views_continues_on_empty_batch_with_cursor(self) -> None:
        pages = [
            [],  # empty round, but cursor advances
            [_post(10, text="hot", views=8_000)],
        ]
        catalog = PagingFakeCatalog(pages)
        pipeline = ClickbaitPipeline(
            catalog_service=catalog,
            analyzer=FakeAnalyzer(),
            page_size=2,
        )
        with unittest.mock.patch.object(
            ClickbaitPipeline, "_min_views_delay", return_value=0
        ):
            result = pipeline.run(PipelineRequest(limit=1, min_views=1_000))
        self.assertEqual(len(result.posts), 1)
        self.assertEqual(result.posts[0].post.post_id, 10)
        self.assertEqual(len(catalog.calls), 2)

    def test_min_views_stops_when_feed_exhausted(self) -> None:
        catalog = FakeCatalog(
            [_post(1, text="a", views=10), _post(2, text="b", views=20)],
            next_from=None,
        )
        pipeline = ClickbaitPipeline(catalog_service=catalog, analyzer=FakeAnalyzer())
        with unittest.mock.patch.object(
            ClickbaitPipeline, "_min_views_delay", return_value=0
        ):
            result = pipeline.run(PipelineRequest(limit=5, min_views=1_000))
        self.assertEqual(result.posts, [])
        self.assertEqual(result.collected, 2)
        self.assertIsNone(result.next_from)

    def test_score_label_clickbait_keeps_scanning(self) -> None:
        pages = [
            [_post(1, text="a"), _post(2, text="b")],
            [_post(3, text="c"), _post(4, text="d")],
            [_post(5, text="e")],
        ]
        catalog = PagingFakeCatalog(pages)

        class ScoreByIdAnalyzer:
            def analyze(self, post: CatalogPost) -> ClickbaitAnalysis:
                # Only post_ids 3 and 5 are clickbait under threshold 0.70.
                score = 0.9 if post.post_id in {3, 5} else 0.1
                return _analysis(post.id or 0, score=score)

        pipeline = ClickbaitPipeline(
            catalog_service=catalog,
            analyzer=ScoreByIdAnalyzer(),
            page_size=2,
        )
        with unittest.mock.patch.object(
            ClickbaitPipeline, "_min_views_delay", return_value=0
        ):
            result = pipeline.run(
                PipelineRequest(limit=2, score_label="clickbait", scoring_threshold=0.70)
            )
        self.assertEqual(len(result.posts), 2)
        self.assertEqual([p.post.post_id for p in result.posts], [3, 5])
        self.assertGreaterEqual(len(catalog.calls), 2)


class PagingFakeCatalog:
    """Returns a different page per collect() call, advancing cursors."""

    def __init__(self, pages: list[list[CatalogPost]]) -> None:
        self.pages = pages
        self.calls: list[dict[str, Any]] = []

    def collect(
        self,
        *,
        count: int = 100,
        start_from: str | None = None,
        pages: int = 1,
        page_size: int = 100,
        query: str | None = None,
        exclude_texts: frozenset[str] | set[str] | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        on_progress=None,
    ) -> CollectResult:
        index = 0
        if start_from and start_from.startswith("p"):
            index = int(start_from[1:])
        self.calls.append(
            {
                "count": count,
                "start_from": start_from,
                "pages": pages,
                "page_size": page_size,
                "query": query,
                "exclude_texts": frozenset(exclude_texts or ()),
                "start_time": start_time,
                "end_time": end_time,
            }
        )
        if index >= len(self.pages):
            return CollectResult(
                fetched=0,
                upsert=UpsertResult(inserted=0),
                posts=[],
                next_from=None,
            )
        batch = self.pages[index][:count]
        if on_progress is not None:
            on_progress(len(batch), count)
        next_index = index + 1
        next_from = f"p{next_index}" if next_index < len(self.pages) else None
        return CollectResult(
            fetched=len(batch),
            upsert=UpsertResult(inserted=len(batch)),
            posts=list(batch),
            next_from=next_from,
        )


if __name__ == "__main__":
    unittest.main()
