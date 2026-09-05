from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime

# Headless Qt for CI / local pytest — must be set before Qt imports.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

from analysis.models import ClickbaitAnalysis, ClickbaitFeatures
from app.gui.worker import PipelineWorker
from domain.pipeline import (
    AnalyzedPost,
    PipelineProgress,
    PipelineRequest,
    PipelineResult,
    PipelineState,
)
from domain.posts import CatalogPost, SOURCE_VK_CATALOG, post_text_key
from ui.formatters import (
    format_post_date,
    format_reason,
    format_score_percent,
    format_views_label,
    human_state,
)
from ui.main_window import MainWindow
from ui.profile_dialog import ProfileSelectDialog, format_profile_label
from ui.widgets.post_card import PostCard
from ui.widgets.results_view import ResultFilter, ResultSort, ResultsView
from app.auth.models import VKProfile
from ui.theme import apply_theme

_APP = QApplication.instance()
if _APP is None:
    _APP = QApplication(["clickbait-parser-tests"])
apply_theme(_APP, persist=False)


class ThemeTests(unittest.TestCase):
    def test_apply_light_and_dark_themes(self) -> None:
        from ui.theme import (
            LIGHT_COLORS,
            apply_theme,
            build_stylesheet,
            get_current_theme,
        )

        apply_theme(_APP, "light", persist=False)
        self.assertEqual(get_current_theme(), "light")
        self.assertIn(LIGHT_COLORS["bg"], _APP.styleSheet())
        apply_theme(_APP, "dark", persist=False)
        self.assertEqual(get_current_theme(), "dark")
        sheet = build_stylesheet(LIGHT_COLORS)
        self.assertIn("#f5f5f7", sheet)
        self.assertIn("#1d1d1f", sheet)


def _post(local_id: int, text: str | None = None, *, views: int = 0) -> CatalogPost:
    return CatalogPost(
        source=SOURCE_VK_CATALOG,
        owner_id=-1,
        post_id=local_id,
        text=text if text is not None else f"text-{local_id}",
        date=datetime.fromtimestamp(1_700_000_000, tz=UTC),
        views=views,
        id=local_id,
    )


def _analyzed(
    local_id: int,
    *,
    score: float,
    text: str | None = None,
    views: int = 0,
) -> AnalyzedPost:
    return AnalyzedPost(
        post=_post(local_id, text=text, views=views),
        analysis=ClickbaitAnalysis(
            post_id=local_id,
            score=score,
            is_clickbait=score >= 0.5,
            reasons=["continuation_bait"] if score >= 0.5 else ["external_link"],
            features=ClickbaitFeatures(),
        ),
    )


class FakePipeline:
    def __init__(
        self,
        *,
        result: PipelineResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result or PipelineResult()
        self.error = error
        self.requests: list[PipelineRequest] = []
        self.progress_callbacks: list = []

    def run(self, request: PipelineRequest, *, on_progress=None) -> PipelineResult:
        self.requests.append(request)
        self.progress_callbacks.append(on_progress)
        if on_progress is not None:
            on_progress(PipelineProgress(PipelineState.COLLECTING, 0, request.limit))
            on_progress(PipelineProgress(PipelineState.ANALYZING, 1, 1))
            on_progress(PipelineProgress(PipelineState.COMPLETED, 1, 1))
        if self.error is not None:
            raise self.error
        return self.result


class PipelineWorkerTests(unittest.TestCase):
    def test_calls_pipeline_with_request_and_emits_progress_and_finished(self) -> None:
        pipeline = FakePipeline(
            result=PipelineResult(posts=[_analyzed(1, score=0.9)], collected=1, analyzed=1)
        )
        worker = PipelineWorker(pipeline_factory=lambda: pipeline)
        request = PipelineRequest(limit=5, query="новости")
        worker.set_request(request)

        progress_events: list[PipelineProgress] = []
        finished_events: list[PipelineResult] = []
        error_events: list[object] = []
        worker.progress.connect(progress_events.append)
        worker.finished.connect(finished_events.append)
        worker.error.connect(error_events.append)

        worker.execute()

        self.assertEqual(len(pipeline.requests), 1)
        self.assertEqual(pipeline.requests[0].limit, 5)
        self.assertEqual(pipeline.requests[0].query, "новости")
        self.assertIsNotNone(pipeline.progress_callbacks[0])
        self.assertEqual(len(progress_events), 3)
        self.assertEqual(progress_events[0].state, PipelineState.COLLECTING)
        self.assertEqual(len(finished_events), 1)
        self.assertEqual(finished_events[0].analyzed, 1)
        self.assertEqual(error_events, [])

    def test_exception_emits_error(self) -> None:
        pipeline = FakePipeline(error=RuntimeError("vk down"))
        worker = PipelineWorker(pipeline_factory=lambda: pipeline)
        worker.set_request(PipelineRequest(limit=1))

        finished_events: list[object] = []
        error_events: list[object] = []
        worker.finished.connect(finished_events.append)
        worker.error.connect(error_events.append)

        worker.execute()

        self.assertEqual(finished_events, [])
        self.assertEqual(len(error_events), 1)
        self.assertIsInstance(error_events[0], RuntimeError)


class MainWindowTests(unittest.TestCase):
    def test_build_request_from_inputs(self) -> None:
        window = MainWindow()
        window._query_input.setText("  новости  ")
        request = window.build_request()
        self.assertEqual(request.limit, 20)
        self.assertEqual(request.query, "новости")

    def test_empty_query_becomes_none(self) -> None:
        window = MainWindow()
        window._query_input.setText("   ")
        self.assertIsNone(window.build_request().query)

    def test_set_running_toggles_button(self) -> None:
        window = MainWindow()
        window.set_running(True)
        self.assertFalse(window._run_button.isEnabled())
        self.assertIn("анализируется", window._run_button.text().lower())
        window.set_running(False)
        self.assertTrue(window._run_button.isEnabled())
        self.assertEqual(window._run_button.text(), "Анализ")

    def test_show_result_and_empty_state(self) -> None:
        window = MainWindow()
        window.show_result(PipelineResult(posts=[], collected=0, analyzed=0))
        self.assertIn(
            "не найдены",
            window.results_view._empty_title.text().lower(),
        )
        self.assertTrue(window.results_view._empty_title.isVisibleTo(window.results_view))
        self.assertIn(
            "поисковый запрос",
            window.results_view._empty_hint.text().lower(),
        )
        self.assertFalse(window.results_view._empty_run_button.isHidden())
        self.assertEqual(window.results_view._empty_run_button.text(), "Анализ")

        # Idle empty state shows Analyse button instead of hint text.
        idle = MainWindow()
        self.assertFalse(idle.results_view._empty_run_button.isHidden())
        self.assertTrue(idle.results_view._empty_title.isHidden())

        window.show_result(
            PipelineResult(
                posts=[_analyzed(1, score=0.9), _analyzed(2, score=0.1)],
                collected=2,
                analyzed=2,
            )
        )
        self.assertEqual(len(window.results_view.visible_posts()), 2)
        self.assertEqual(
            window._stats_label.text(),
            "2 posts · 1 clickbait · 1 normal",
        )

    def test_load_more_uses_cursor_and_appends(self) -> None:
        window = MainWindow()
        self.assertFalse(window.next_page_enabled)

        requests: list[PipelineRequest] = []
        window.run_requested.connect(requests.append)

        window.show_result(
            PipelineResult(
                posts=[_analyzed(1, score=0.9), _analyzed(2, score=0.1)],
                collected=2,
                analyzed=2,
                next_from="cursor-2",
            )
        )
        # Short page fits the viewport → infinite scroll may already have requested.
        if not requests:
            self.assertTrue(window.next_page_enabled)
            window._on_load_more_requested()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].start_from, "cursor-2")
        self.assertEqual(requests[0].limit, 20)
        self.assertTrue(window._pending_append)
        self.assertFalse(window.next_page_enabled)
        self.assertIn(post_text_key("text-1"), requests[0].exclude_texts)
        self.assertIn(post_text_key("text-2"), requests[0].exclude_texts)

        window.show_result(
            PipelineResult(
                posts=[_analyzed(3, score=0.2)],
                collected=1,
                analyzed=1,
                next_from=None,
            )
        )
        self.assertEqual(len(window.results_view.posts), 3)

    def test_load_more_preserves_result_filter(self) -> None:
        window = MainWindow()
        requests: list[PipelineRequest] = []
        window.run_requested.connect(requests.append)
        window.show_result(
            PipelineResult(
                posts=[_analyzed(1, score=0.9), _analyzed(2, score=0.1)],
                collected=2,
                analyzed=2,
                next_from="cursor-2",
            )
        )
        window.results_view.set_filter(ResultFilter.CLICKBAIT)
        self.assertEqual(window.results_view.current_filter(), ResultFilter.CLICKBAIT)

        if not requests:
            window._on_load_more_requested()
        # Finish the in-flight page (ignore auto-chained requests after append).
        first = requests[0]
        window.show_result(
            PipelineResult(
                posts=[_analyzed(3, score=0.95), _analyzed(4, score=0.05)],
                collected=2,
                analyzed=2,
                next_from=None,
            )
        )
        self.assertEqual(first.limit, 20)
        self.assertEqual(window.results_view.current_filter(), ResultFilter.CLICKBAIT)
        visible = window.results_view.visible_posts()
        self.assertEqual(len(visible), 2)
        self.assertTrue(all(item.analysis.is_clickbait for item in visible))

    def test_missing_next_from_exhausts_feed(self) -> None:
        window = MainWindow()
        window.show_result(
            PipelineResult(
                posts=[_analyzed(i, score=0.1) for i in range(1, 35)],
                collected=34,
                analyzed=34,
                next_from=None,
            )
        )
        self.assertFalse(window.next_page_enabled)
        self.assertTrue(window._feed_exhausted)

    def test_empty_append_without_cursor_exhausts_feed(self) -> None:
        window = MainWindow()
        window.show_result(
            PipelineResult(
                posts=[_analyzed(1, score=0.9), _analyzed(2, score=0.1)],
                collected=2,
                analyzed=2,
                next_from="c1",
            )
        )
        window._pending_append = True
        window.show_result(
            PipelineResult(posts=[], collected=0, analyzed=0, next_from=None)
        )
        self.assertFalse(window.next_page_enabled)
        self.assertTrue(window._feed_exhausted)

    def test_empty_append_with_cursor_keeps_searching(self) -> None:
        window = MainWindow()
        requests: list[PipelineRequest] = []
        window.run_requested.connect(requests.append)
        window.results_view.set_min_views(5_000)
        window.show_result(
            PipelineResult(
                posts=[_analyzed(1, score=0.1, views=10)],
                collected=1,
                analyzed=1,
                next_from="c1",
            )
        )
        requests.clear()
        window._pending_append = True
        window.show_result(
            PipelineResult(posts=[], collected=0, analyzed=0, next_from="c2")
        )
        self.assertFalse(window._feed_exhausted)
        self.assertEqual(window._next_from, "c2")
        # Empty round with a cursor must allow / trigger another search.
        self.assertTrue(window._pending_append or window._can_load_more())

    def test_query_edit_does_not_change_load_more_query(self) -> None:
        window = MainWindow()
        window._session_query = "новости"
        requests: list[PipelineRequest] = []
        window.run_requested.connect(requests.append)
        window.show_result(
            PipelineResult(
                posts=[_analyzed(1, score=0.9)],
                collected=1,
                analyzed=1,
                next_from="cursor-keep",
            )
        )
        window._query_input.setText("другой запрос")
        if not requests:
            window._on_load_more_requested()
        self.assertEqual(requests[0].query, "новости")
        self.assertEqual(requests[0].start_from, "cursor-keep")

    def test_analysis_resets_pagination(self) -> None:
        window = MainWindow()
        requests: list[PipelineRequest] = []
        window.run_requested.connect(requests.append)
        window.show_result(
            PipelineResult(
                posts=[_analyzed(1, score=0.9)],
                collected=1,
                analyzed=1,
                next_from="cursor-x",
            )
        )
        # Drop any auto load-more from the short first page.
        requests.clear()
        window._pending_append = False
        window._on_run_clicked()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].start_from, None)
        self.assertFalse(window._pending_append)
        window.set_running(True)
        self.assertFalse(window.next_page_enabled)

    def test_build_request_includes_min_views(self) -> None:
        window = MainWindow()
        window.results_view.set_min_views(1_500)
        request = window.build_request()
        self.assertEqual(request.min_views, 1_500)
        self.assertEqual(request.limit, 20)

    def test_min_views_autofills_until_page_size(self) -> None:
        window = MainWindow()
        requests: list[PipelineRequest] = []
        window.run_requested.connect(requests.append)

        low = _analyzed(1, score=0.1, views=10)
        high = _analyzed(2, score=0.1, views=5_000)
        window.show_result(
            PipelineResult(posts=[low, high], collected=2, analyzed=2, next_from="c1")
        )
        # Ignore scroll-triggered load-more from a short first page.
        window._pending_append = False
        requests.clear()
        window.results_view.set_min_views(1_000)
        _APP.processEvents()
        # Changing min-views should request another page while visible < 20.
        self.assertGreaterEqual(len(requests), 1)
        self.assertEqual(requests[0].min_views, 1_000)
        self.assertEqual(requests[0].start_from, "c1")
        self.assertEqual(len(window.results_view.visible_posts()), 1)
        self.assertTrue(window._pending_append)

    def test_min_views_reopens_exhausted_feed(self) -> None:
        """Changing min-views must search again even if feed was marked exhausted."""
        window = MainWindow()
        requests: list[PipelineRequest] = []
        window.run_requested.connect(requests.append)
        posts = [_analyzed(i, score=0.1, views=50) for i in range(1, 6)]
        window.show_result(
            PipelineResult(posts=posts, collected=5, analyzed=5, next_from="c9")
        )
        window._feed_exhausted = True
        window.results_view.set_feed_exhausted(True)
        window._pending_append = False
        requests.clear()

        window.results_view.set_min_views(10_000)
        _APP.processEvents()

        self.assertFalse(window._feed_exhausted)
        self.assertGreaterEqual(len(requests), 1)
        self.assertEqual(requests[0].min_views, 10_000)
        self.assertEqual(requests[0].start_from, "c9")

    def test_min_views_stops_when_enough_visible(self) -> None:
        window = MainWindow()
        requests: list[PipelineRequest] = []
        window.run_requested.connect(requests.append)
        posts = [_analyzed(i, score=0.1, views=2_000) for i in range(1, 25)]
        window.show_result(
            PipelineResult(posts=posts, collected=24, analyzed=24, next_from="c1")
        )
        window._pending_append = False
        requests.clear()
        window.results_view.set_min_views(1_000)
        _APP.processEvents()
        # Already have >= PAGE_SIZE visible — no fill-up autofill.
        fill_ups = [r for r in requests if r.limit < 20]
        self.assertEqual(fill_ups, [])
        self.assertGreaterEqual(len(window.results_view.visible_posts()), 20)

        window = MainWindow()
        requests = []
        window.run_requested.connect(requests.append)
        window.show_result(
            PipelineResult(
                posts=[_analyzed(1, score=0.9)],
                collected=1,
                analyzed=1,
                next_from="cursor-1",
            )
        )
        window._pending_append = False
        window.results_view.set_loading_more(False)
        requests.clear()
        window.results_view.reset_near_bottom_gate()
        window.results_view.set_load_more_enabled(True)
        window.results_view._check_near_bottom()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].limit, 20)
        self.assertTrue(window.results_view._loading_more)
        self.assertFalse(window.results_view._loading_footer.isHidden())
        # Guard against repeat until next page finishes.
        window.results_view._check_near_bottom()
        self.assertEqual(len(requests), 1)

    def test_short_clickbait_list_reloads_at_bottom(self) -> None:
        """Filtered short lists stay at bottom — pagination must not latch forever."""
        window = MainWindow()
        requests: list[PipelineRequest] = []
        window.run_requested.connect(requests.append)
        posts = [_analyzed(i, score=0.9, views=2_000) for i in range(1, 4)]
        window.show_result(
            PipelineResult(posts=posts, collected=3, analyzed=3, next_from="c-next")
        )
        window.results_view.set_filter(ResultFilter.CLICKBAIT)
        window.results_view.set_min_views(1_000)
        window._pending_append = False
        window.results_view.set_loading_more(False)
        requests.clear()
        window._sync_load_more()
        _APP.processEvents()
        self.assertGreaterEqual(len(requests), 1)
        self.assertEqual(requests[0].start_from, "c-next")

    def test_loading_more_footer_hides_after_result(self) -> None:
        window = MainWindow()
        window.show_result(
            PipelineResult(
                posts=[_analyzed(1, score=0.9)],
                collected=1,
                analyzed=1,
                next_from="cursor-1",
            )
        )
        window.results_view.set_loading_more(True)
        self.assertTrue(window.results_view._loading_more)
        self.assertFalse(window.results_view._loading_footer.isHidden())
        # Prevent auto load-more after show_result (short list fits viewport).
        window._feed_exhausted = True
        window._pending_append = True
        window.show_result(
            PipelineResult(
                posts=[_analyzed(2, score=0.2)],
                collected=1,
                analyzed=1,
                next_from=None,
            )
        )
        self.assertFalse(window.results_view._loading_more)
        self.assertTrue(window.results_view._loading_footer.isHidden())
        self.assertEqual(len(window.results_view.posts), 2)

    def test_label_requested_persists_via_dataset_service(self) -> None:
        from domain.dataset import DatasetLabel, DatasetStats

        class FakeDataset:
            def __init__(self) -> None:
                self.labeled: list[tuple[int, DatasetLabel]] = []
                self.labels: dict[int, DatasetLabel] = {}

            def label_analyzed_post(self, item, label: DatasetLabel, note=None):
                post_id = item.post.id
                assert post_id is not None
                self.labeled.append((post_id, label))
                self.labels[post_id] = label
                return item

            def get_labels_for_posts(self, post_ids: list[int]) -> dict[int, DatasetLabel]:
                return {i: self.labels[i] for i in post_ids if i in self.labels}

            def get_dataset_stats(self) -> DatasetStats:
                by = {
                    DatasetLabel.CLICKBAIT: sum(
                        1 for v in self.labels.values() if v == DatasetLabel.CLICKBAIT
                    ),
                    DatasetLabel.NORMAL: sum(
                        1 for v in self.labels.values() if v == DatasetLabel.NORMAL
                    ),
                    DatasetLabel.BORDERLINE: sum(
                        1 for v in self.labels.values() if v == DatasetLabel.BORDERLINE
                    ),
                }
                return DatasetStats(
                    total_labeled=len(self.labels),
                    unlabeled=0,
                    by_label=by,
                    rule_clickbait=0,
                    rule_normal=0,
                    disagreement_human_clickbait_rule_normal=0,
                    disagreement_human_normal_rule_clickbait=0,
                )

        window = MainWindow()
        fake = FakeDataset()
        window.set_dataset_service(fake)
        window.show_result(
            PipelineResult(
                posts=[_analyzed(11, score=0.9), _analyzed(12, score=0.1)],
                collected=2,
                analyzed=2,
                next_from=None,
            )
        )
        window._on_label_requested(11, DatasetLabel.CLICKBAIT)
        self.assertEqual(fake.labeled, [(11, DatasetLabel.CLICKBAIT)])
        self.assertEqual(window._labeled_stats_label.text(), "labeled 1  ↑1 ↓0")

    def test_show_labeled_library(self) -> None:
        from domain.dataset import DatasetLabel, DatasetStats

        class FakeDataset:
            def label_post(self, post_id, label, note=None):
                return label

            def get_labels_for_posts(self, post_ids):
                return {}

            def get_dataset_stats(self):
                return DatasetStats(
                    total_labeled=2,
                    unlabeled=0,
                    by_label={
                        DatasetLabel.CLICKBAIT: 1,
                        DatasetLabel.NORMAL: 1,
                        DatasetLabel.BORDERLINE: 0,
                    },
                    rule_clickbait=0,
                    rule_normal=0,
                    disagreement_human_clickbait_rule_normal=0,
                    disagreement_human_normal_rule_clickbait=0,
                )

            def list_labeled_analyzed(self, *, limit=5000):
                posts = [_analyzed(21, score=0.9), _analyzed(22, score=0.2)]
                labels = {
                    21: DatasetLabel.CLICKBAIT,
                    22: DatasetLabel.NORMAL,
                }
                return posts, labels

        window = MainWindow()
        window.set_dataset_service(FakeDataset())
        window.show_result(
            PipelineResult(
                posts=[_analyzed(1, score=0.5)],
                collected=1,
                analyzed=1,
            )
        )
        window._show_labeled_library()
        self.assertTrue(window._showing_labeled_library)
        self.assertEqual(window.results_view.current_filter(), ResultFilter.LABELED)
        self.assertEqual(len(window.results_view.visible_posts()), 2)
        window._on_filter_changed(ResultFilter.ALL)
        self.assertFalse(window._showing_labeled_library)
        self.assertEqual(len(window.results_view.posts), 1)

    def test_show_error(self) -> None:
        window = MainWindow()
        window.show_error("network timeout")
        self.assertFalse(window._error_panel.isHidden())
        self.assertIn("network timeout", window._error_detail.text())


class ResultsViewTests(unittest.TestCase):
    def test_filter_clickbait_and_normal(self) -> None:
        view = ResultsView()
        view.set_results(
            [
                _analyzed(1, score=0.9),
                _analyzed(2, score=0.1),
                _analyzed(3, score=0.8),
            ]
        )
        view.set_filter(ResultFilter.CLICKBAIT)
        self.assertEqual(len(view.visible_posts()), 2)
        view.set_filter(ResultFilter.NORMAL)
        self.assertEqual(len(view.visible_posts()), 1)
        view.set_filter(ResultFilter.ALL)
        self.assertEqual(len(view.visible_posts()), 3)

    def test_append_results_is_incremental(self) -> None:
        view = ResultsView()
        view.resize(800, 600)
        view.show()
        view.set_results([_analyzed(1, score=0.9), _analyzed(2, score=0.1)])
        first_cards = [
            view._cards_layout.itemAt(i).widget()
            for i in range(view._cards_layout.count())
            if view._cards_layout.itemAt(i).widget() is not None
            and isinstance(view._cards_layout.itemAt(i).widget(), PostCard)
        ]
        self.assertEqual(len(first_cards), 2)
        first_ids = {id(card) for card in first_cards}

        view.append_results([_analyzed(3, score=0.2), _analyzed(4, score=0.8)])
        cards = [
            view._cards_layout.itemAt(i).widget()
            for i in range(view._cards_layout.count())
            if view._cards_layout.itemAt(i).widget() is not None
            and isinstance(view._cards_layout.itemAt(i).widget(), PostCard)
        ]
        self.assertEqual(len(cards), 4)
        # Existing widgets must be reused (no full rebuild).
        self.assertTrue(first_ids.issubset({id(card) for card in cards}))
        self.assertEqual(len(view.posts), 4)

    def test_scoring_mode_changes_filter(self) -> None:
        from domain.scoring import ScoringMode

        view = ResultsView()
        view.set_ml_ready(True)
        view.set_results(
            [
                _analyzed(1, score=0.80),
                _analyzed(2, score=0.20),
            ]
        )
        view.update_ml_scores({1: 0.10, 2: 0.95})
        view.set_scoring_mode(ScoringMode.RULES)
        view.set_filter(ResultFilter.CLICKBAIT)
        self.assertEqual([p.post.id for p in view.visible_posts()], [1])

        view.set_scoring_mode(ScoringMode.ML)
        self.assertEqual([p.post.id for p in view.visible_posts()], [2])

        view.set_scoring_mode(ScoringMode.RULES_ML)
        # 0.80*0.3+0.10*0.7=0.31; 0.20*0.3+0.95*0.7=0.725
        self.assertEqual([p.post.id for p in view.visible_posts()], [2])

    def test_filter_labeled(self) -> None:
        from domain.dataset import DatasetLabel

        view = ResultsView()
        view.set_results(
            [
                _analyzed(1, score=0.9),
                _analyzed(2, score=0.1),
                _analyzed(3, score=0.8),
            ]
        )
        view.set_human_labels({1: DatasetLabel.CLICKBAIT, 3: DatasetLabel.NORMAL})
        view.set_filter(ResultFilter.LABELED)
        self.assertEqual(
            [p.post.post_id for p in view.visible_posts()],
            [1, 3],
        )

    def test_sort_and_min_views(self) -> None:
        view = ResultsView()
        view.set_results(
            [
                _analyzed(1, score=0.9, views=10),
                _analyzed(2, score=0.1, views=500),
                _analyzed(3, score=0.8, views=100),
            ]
        )
        view.set_sort(ResultSort.VIEWS_DESC)
        self.assertEqual(
            [p.post.post_id for p in view.visible_posts()],
            [2, 3, 1],
        )
        view.set_min_views(100)
        self.assertEqual(
            [p.post.post_id for p in view.visible_posts()],
            [2, 3],
        )
        view.set_sort(ResultSort.VIEWS_ASC)
        self.assertEqual(
            [p.post.post_id for p in view.visible_posts()],
            [3, 2],
        )

    def test_sort_by_clickbait_score(self) -> None:
        view = ResultsView()
        view.set_results(
            [
                _analyzed(1, score=0.4),
                _analyzed(2, score=0.95),
                _analyzed(3, score=0.7),
            ]
        )
        view.set_sort(ResultSort.SCORE_DESC)
        self.assertEqual(
            [p.post.post_id for p in view.visible_posts()],
            [2, 3, 1],
        )
        view.set_sort(ResultSort.SCORE_ASC)
        self.assertEqual(
            [p.post.post_id for p in view.visible_posts()],
            [1, 3, 2],
        )

    def test_dedupes_identical_texts(self) -> None:
        view = ResultsView()
        view.set_results(
            [
                _analyzed(1, score=0.9, text="Один и тот же текст"),
                _analyzed(2, score=0.1, text="один и тот же   текст"),
                _analyzed(3, score=0.8, text="Другой текст"),
            ]
        )
        self.assertEqual(len(view.posts), 2)
        self.assertEqual(
            [p.post.post_id for p in view.posts],
            [1, 3],
        )


class FormattersTests(unittest.TestCase):
    def test_score_and_reason_and_date(self) -> None:
        self.assertEqual(format_score_percent(0.82), "82%")
        self.assertEqual(format_reason("continuation_bait"), "Продолжение по ссылке")
        when = format_post_date(datetime(2026, 9, 4, 1, 1, tzinfo=UTC))
        self.assertIn("сент.", when)
        self.assertIn("2026", when)
        self.assertEqual(human_state(PipelineState.ANALYZING), "Анализ постов")
        self.assertIn("просмотр", format_views_label(1))
        self.assertIn("12.5K", format_views_label(12_500))


class PostCardTests(unittest.TestCase):
    def test_renders_percent_and_copies_text(self) -> None:
        card = PostCard()
        item = _analyzed(1, score=0.82, text="полный текст поста", views=1500)
        card.set_post(item)
        self.assertEqual(card._score.text(), "82%")
        self.assertEqual(card._prediction.text(), "🔴 Clickbait")
        self.assertEqual(card._rules_row._value_label.text(), "82%")
        self.assertEqual(card._ml_row._value_label.text(), "—")
        self.assertIn("82%", card._final_row._value_label.text())
        self.assertIn("просмотр", card._meta_label.text().lower())
        card._on_copy()
        self.assertEqual(QApplication.clipboard().text(), "полный текст поста")
        self.assertEqual(card._copy_button.toolTip(), "Copied")

    def test_label_buttons_emit_signal(self) -> None:
        from domain.dataset import DatasetLabel

        card = PostCard()
        item = _analyzed(7, score=0.9, text="разметить")
        card.set_post(item)
        events: list[tuple[int, DatasetLabel]] = []
        card.label_requested.connect(lambda pid, label: events.append((pid, label)))
        card._btn_clickbait.click()
        self.assertEqual(events, [(7, DatasetLabel.CLICKBAIT)])
        self.assertTrue(card._btn_clickbait.isChecked())
        card._btn_normal.click()
        self.assertEqual(events[-1], (7, DatasetLabel.NORMAL))
        self.assertTrue(card._btn_normal.isChecked())
        self.assertFalse(card._btn_clickbait.isChecked())


class FakeProfileStore:
    def __init__(self, profiles: list[VKProfile] | None = None) -> None:
        self.profiles = list(profiles or [])
        self.logout_calls: list[int] = []

    def get_profiles(self) -> list[VKProfile]:
        return list(self.profiles)

    def logout(self, profile_id: int) -> None:
        self.logout_calls.append(profile_id)
        self.profiles = [p for p in self.profiles if p.id != profile_id]


class ProfileSelectDialogTests(unittest.TestCase):
    def test_format_profile_label(self) -> None:
        label = format_profile_label(
            VKProfile(
                id=3,
                provider="vk",
                provider_user_id=42,
                first_name="Иван",
                last_name="Петров",
            )
        )
        self.assertIn("#3", label)
        self.assertIn("Иван Петров", label)
        self.assertIn("vk:42", label)

    def test_lists_profiles_and_accepts_selection(self) -> None:
        store = FakeProfileStore(
            [
                VKProfile(id=1, provider="vk", provider_user_id=10, first_name="A"),
                VKProfile(id=2, provider="vk", provider_user_id=20, first_name="B"),
            ]
        )

        def auth_factory(*, on_status=None, on_qr=None):
            return None  # type: ignore[return-value]

        dialog = ProfileSelectDialog(
            profiles=store,
            auth_factory=auth_factory,
            initial_profile_id=2,
        )
        self.assertEqual(dialog._list.count(), 2)
        self.assertEqual(dialog._current_profile_id(), 2)
        dialog._accept_if_selected()
        self.assertEqual(dialog.selected_profile_id, 2)
        self.assertEqual(dialog.result(), dialog.DialogCode.Accepted)

    def test_show_qr_displays_pixmap(self) -> None:
        store = FakeProfileStore([])

        def auth_factory(*, on_status=None, on_qr=None):
            return None  # type: ignore[return-value]

        dialog = ProfileSelectDialog(profiles=store, auth_factory=auth_factory)
        dialog.show_qr("https://qr.vk.ru/ca?q=ui-test")
        self.assertFalse(dialog._qr_label.isHidden())
        self.assertFalse(dialog._qr_label.pixmap() is None)
        dialog.clear_qr()
        self.assertTrue(dialog._qr_label.isHidden())

    def test_remove_profile_refreshes_list(self) -> None:
        store = FakeProfileStore(
            [
                VKProfile(id=1, provider="vk", provider_user_id=10, first_name="A"),
                VKProfile(id=2, provider="vk", provider_user_id=20, first_name="B"),
            ]
        )

        def auth_factory(*, on_status=None, on_qr=None):
            return None  # type: ignore[return-value]

        dialog = ProfileSelectDialog(
            profiles=store,
            auth_factory=auth_factory,
            initial_profile_id=1,
        )
        # Bypass confirmation dialog
        dialog._profiles.logout(1)
        dialog.reload()
        self.assertEqual(dialog._list.count(), 1)
        self.assertEqual(dialog._current_profile_id(), 2)


if __name__ == "__main__":
    unittest.main()
