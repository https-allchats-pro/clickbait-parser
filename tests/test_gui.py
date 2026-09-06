from __future__ import annotations

import os
import unittest
from datetime import UTC, date, datetime

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
from domain.posts import CatalogPost, SOURCE_VK_CATALOG
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
from ui.widgets.results_view import ResultFilter, ResultSort, ResultsView, TimePreset
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


def _post(
    local_id: int,
    text: str | None = None,
    *,
    views: int = 0,
    at: datetime | None = None,
) -> CatalogPost:
    return CatalogPost(
        source=SOURCE_VK_CATALOG,
        owner_id=-1,
        post_id=local_id,
        text=text if text is not None else f"text-{local_id}",
        date=at or datetime.fromtimestamp(1_700_000_000, tz=UTC),
        views=views,
        id=local_id,
    )


def _analyzed(
    local_id: int,
    *,
    score: float,
    text: str | None = None,
    views: int = 0,
    at: datetime | None = None,
) -> AnalyzedPost:
    return AnalyzedPost(
        post=_post(local_id, text=text, views=views, at=at),
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
        request = window.build_request(query=window._query_input.text().strip() or None)
        self.assertEqual(request.limit, 20)
        self.assertEqual(request.query, "новости")

    def test_empty_query_becomes_none(self) -> None:
        window = MainWindow()
        window._query_input.setText("   ")
        self.assertIsNone(window.build_request(query=None).query)

    def test_enter_adds_search_terms(self) -> None:
        window = MainWindow()
        window._query_input.setText("продолжение")
        window._search._on_return_pressed()
        window._query_input.setText("новости")
        window._search._on_return_pressed()
        self.assertEqual(window._search.terms(), ["продолжение", "новости"])

    def test_multi_query_analyse_chains_async_steps(self) -> None:
        window = MainWindow()
        requests: list[PipelineRequest] = []
        window.run_requested.connect(requests.append)
        window._search.set_terms(["alpha", "beta"])
        window._on_run_clicked()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].query, "alpha")
        self.assertEqual(window._query_step_queue, ["beta"])
        # First word finishes → next word is queued asynchronously.
        window.show_result(
            PipelineResult(
                posts=[_analyzed(1, score=0.9)],
                collected=1,
                analyzed=1,
                next_from="c-a",
            )
        )
        window.set_running(False)
        _APP.processEvents()
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[1].query, "beta")
        self.assertTrue(window._pending_append)

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
        self.assertTrue(window.next_page_enabled)
        window._on_next_page_requested()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].start_from, "cursor-2")
        self.assertEqual(requests[0].limit, 20)
        self.assertTrue(window._pending_append)
        self.assertTrue(window._advance_after_fetch)
        self.assertFalse(window._can_fetch_more())
        self.assertEqual(requests[0].exclude_texts, frozenset())

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

        window._fetch_more_page()
        first = requests[0]
        self.assertEqual(first.score_label, "clickbait")
        # Fill remaining slots on the first clickbait page (1 already loaded).
        self.assertEqual(first.limit, 19)
        window.show_result(
            PipelineResult(
                posts=[_analyzed(3, score=0.95), _analyzed(4, score=0.05)],
                collected=2,
                analyzed=2,
                next_from=None,
            )
        )
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
        self.assertFalse(window._can_fetch_more())
        self.assertTrue(window._feed_exhausted)
        # Local next page is still available from the buffered posts.
        self.assertTrue(window.results_view.can_go_next_local())
        self.assertEqual(window.results_view.page_count(), 2)

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
        window._fetch_more_page()
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
        # Already have >= page size in the filtered buffer — no fill-up autofill.
        fill_ups = [r for r in requests if r.limit < 20]
        self.assertEqual(fill_ups, [])
        self.assertGreaterEqual(len(window.results_view.filtered_posts()), 20)
        self.assertEqual(len(window.results_view.visible_posts()), 20)

    def test_pager_next_fetches_when_past_buffer(self) -> None:
        window = MainWindow()
        requests: list[PipelineRequest] = []
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

        window._on_next_page_requested()
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].limit, 20)
        self.assertTrue(window._advance_after_fetch)
        self.assertEqual(window._pending_target_page, 2)
        self.assertTrue(window.results_view._loading_more)

        window.show_result(
            PipelineResult(
                posts=[_analyzed(i, score=0.1) for i in range(2, 22)],
                collected=20,
                analyzed=20,
                next_from="cursor-2",
            ),
            append=True,
            target_page=2,
        )
        self.assertEqual(len(window.results_view.posts), 21)
        self.assertEqual(window.results_view.loaded_page_count(), 2)
        self.assertEqual(window.results_view.current_page(), 2)
        self.assertEqual(len(window.results_view.visible_posts()), 1)
        self.assertEqual(window.results_view.visible_posts()[0].post.id, 21)

    def test_clickbait_filter_keeps_fetching_until_next_page(self) -> None:
        """Clickbait tab asks the worker for score_label fill so Next gets matches."""
        window = MainWindow()
        requests: list[PipelineRequest] = []
        window.run_requested.connect(requests.append)
        # 20 clickbait = exactly one filtered page.
        clickbait = [_analyzed(i, score=0.9) for i in range(1, 21)]
        window.show_result(
            PipelineResult(
                posts=clickbait,
                collected=20,
                analyzed=20,
                next_from="c1",
            )
        )
        window.results_view.set_filter(ResultFilter.CLICKBAIT)
        window._pending_append = False
        window._empty_page_retries = 0
        requests.clear()

        window._on_next_page_requested()
        self.assertEqual(window._pending_target_page, 2)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].score_label, "clickbait")
        self.assertEqual(requests[0].target_page, 2)
        self.assertEqual(requests[0].limit, 20)
        self.assertTrue(requests[0].needs_filtered_fill)

        # Worker returns only matching clickbait (filtered fill).
        window._pending_append = False
        window.show_result(
            PipelineResult(
                posts=[_analyzed(i, score=0.95) for i in range(200, 220)],
                collected=200,
                analyzed=20,
                next_from="c3",
            ),
            append=True,
            target_page=2,
        )
        self.assertEqual(window.results_view.loaded_page_count(), 2)
        self.assertEqual(window.results_view.current_page(), 2)
        self.assertFalse(window._advance_after_fetch)

    def test_clickbait_filter_autofills_short_first_page(self) -> None:
        window = MainWindow()
        requests: list[PipelineRequest] = []
        window.run_requested.connect(requests.append)
        window.show_result(
            PipelineResult(
                posts=[_analyzed(i, score=0.9) for i in range(1, 6)],
                collected=5,
                analyzed=5,
                next_from="c1",
            )
        )
        window._pending_append = False
        requests.clear()
        window.results_view._on_filter_clicked(1)
        _APP.processEvents()
        self.assertEqual(window.results_view.current_filter(), ResultFilter.CLICKBAIT)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].score_label, "clickbait")
        self.assertEqual(requests[0].limit, 15)

    def test_pager_page_button_fetches_beyond_buffer(self) -> None:
        """Clicking page 3 while on page 1 must fetch, not only step to page 2."""
        window = MainWindow()
        requests: list[PipelineRequest] = []
        window.run_requested.connect(requests.append)
        window.show_result(
            PipelineResult(
                posts=[_analyzed(i, score=0.9) for i in range(1, 41)],
                collected=40,
                analyzed=40,
                next_from="c1",
            )
        )
        window.results_view.set_filter(ResultFilter.CLICKBAIT)
        window._pending_append = False
        self.assertEqual(window.results_view.current_page(), 1)
        self.assertEqual(window.results_view.loaded_page_count(), 2)
        requests.clear()

        window._on_page_requested(3)
        self.assertEqual(window._pending_target_page, 3)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].target_page, 3)
        self.assertEqual(requests[0].limit, 20)

        window._pending_append = False
        window.show_result(
            PipelineResult(
                posts=[_analyzed(i, score=0.95) for i in range(200, 220)],
                collected=20,
                analyzed=20,
                next_from="c2",
            ),
            append=True,
            target_page=3,
        )
        self.assertEqual(window.results_view.loaded_page_count(), 3)
        self.assertEqual(window.results_view.current_page(), 3)

    def test_show_result_keeps_append_when_flag_false_but_pending(self) -> None:
        """Controller race used to pass append=False and wipe the feed."""
        window = MainWindow()
        window.show_result(
            PipelineResult(
                posts=[_analyzed(i, score=0.1) for i in range(1, 21)],
                collected=20,
                analyzed=20,
                next_from="c1",
            )
        )
        window._pending_append = True
        window._advance_after_fetch = True
        window._pending_target_page = 2
        window.show_result(
            PipelineResult(
                posts=[_analyzed(i, score=0.1) for i in range(21, 41)],
                collected=20,
                analyzed=20,
                next_from="c2",
            ),
            append=False,  # bogus flag from race
            target_page=2,
        )
        self.assertEqual(len(window.results_view.posts), 40)
        self.assertEqual(window.results_view.current_page(), 2)

    def test_pager_prev_stays_in_buffer(self) -> None:
        window = MainWindow()
        requests: list[PipelineRequest] = []
        window.run_requested.connect(requests.append)
        window.show_result(
            PipelineResult(
                posts=[_analyzed(i, score=0.1) for i in range(1, 45)],
                collected=44,
                analyzed=44,
                next_from="c-next",
            )
        )
        requests.clear()
        self.assertEqual(window.results_view.loaded_page_count(), 3)
        self.assertEqual(window.results_view.page_count(), 4)  # + provisional next
        window._on_page_requested(2)
        self.assertEqual(window.results_view.current_page(), 2)
        self.assertEqual(len(window.results_view.visible_posts()), 20)
        window._on_prev_page_requested()
        self.assertEqual(window.results_view.current_page(), 1)
        self.assertEqual(requests, [])

    def test_pager_page_size_change_reslices(self) -> None:
        window = MainWindow()
        window.show_result(
            PipelineResult(
                posts=[_analyzed(i, score=0.1) for i in range(1, 16)],
                collected=15,
                analyzed=15,
                next_from=None,
            )
        )
        window.results_view.set_page_size(5, emit=True)
        window._on_page_size_changed(5)
        self.assertEqual(window.results_view.page_size(), 5)
        self.assertEqual(window.results_view.page_count(), 3)
        self.assertEqual(len(window.results_view.visible_posts()), 5)

    def test_pager_next_stays_enabled_when_exhausted(self) -> None:
        window = MainWindow()
        window.show_result(
            PipelineResult(
                posts=[_analyzed(1, score=0.9)],
                collected=1,
                analyzed=1,
                next_from=None,
            )
        )
        self.assertFalse(window._can_fetch_more())
        self.assertFalse(window.results_view.can_go_next_local())
        # Forward stays clickable even when VK reported no cursor.
        self.assertTrue(window.results_view._pager._next.isEnabled())

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

    def test_append_results_extends_buffer(self) -> None:
        view = ResultsView()
        posts = [_analyzed(i, score=0.1) for i in range(1, 13)]
        view.set_results(posts[:6])
        view.append_results(posts[6:])
        self.assertEqual(len(view.posts), 12)
        view.set_page_size(5)
        view.go_to_page(1)
        self.assertEqual(view.page_size(), 5)
        self.assertEqual(len(view.visible_posts()), 5)
        self.assertEqual(view.page_count(), 3)
        view.go_next_page()
        self.assertEqual(view.current_page(), 2)
        self.assertEqual(len(view.visible_posts()), 5)

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

    def test_time_window_presets(self) -> None:
        from datetime import timedelta

        view = ResultsView()
        start, end = view.current_time_window()
        self.assertLess(start, end)
        self.assertAlmostEqual(end - start, 24 * 3600, delta=5)

        view.set_time_preset(TimePreset.WEEK)
        start, end = view.current_time_window()
        self.assertAlmostEqual(end - start, 7 * 24 * 3600, delta=5)

        view.set_time_preset(TimePreset.MONTH)
        start, end = view.current_time_window()
        self.assertAlmostEqual(end - start, 30 * 24 * 3600, delta=5)

        view.set_custom_period(date(2026, 9, 1), date(2026, 9, 3))
        start, end = view.current_time_window()
        self.assertEqual(view.current_time_preset(), TimePreset.CUSTOM)
        self.assertLess(start, end)
        # Custom spans 1st 00:00 → 3rd 23:59:59 ≈ 3 days.
        self.assertGreaterEqual(end - start, 2 * 24 * 3600)
        self.assertLessEqual(end - start, 3 * 24 * 3600 + 5)

    def test_build_request_includes_time_window(self) -> None:
        window = MainWindow()
        window.results_view.set_time_preset(TimePreset.WEEK)
        request = window.build_request()
        self.assertIsNotNone(request.start_time)
        self.assertIsNotNone(request.end_time)
        self.assertAlmostEqual(
            int(request.end_time) - int(request.start_time),
            7 * 24 * 3600,
            delta=5,
        )

    def test_session_time_window_frozen_across_pages(self) -> None:
        window = MainWindow()
        window.results_view.set_time_preset(TimePreset.MONTH)
        window._session_start_time = 1_700_000_000
        window._session_end_time = 1_700_000_000 + 30 * 24 * 3600
        first = window.build_request()
        second = window.build_request(start_from="cursor-2", append=True)
        self.assertEqual(first.start_time, second.start_time)
        self.assertEqual(first.end_time, second.end_time)
        self.assertEqual(first.start_time, 1_700_000_000)

    def test_time_watermark_keeps_pagination_without_next_from(self) -> None:
        """Wide VK windows often omit next_from — keep a provisional next page."""
        window = MainWindow()
        window.results_view.set_time_preset(TimePreset.MONTH)
        window._session_start_time = 1_700_000_000
        window._session_end_time = 1_700_000_000 + 30 * 24 * 3600
        posts = [
            _analyzed(
                i,
                score=0.1,
                at=datetime.fromtimestamp(1_700_500_000 - i * 100, tz=UTC),
            )
            for i in range(1, 21)
        ]
        window.show_result(
            PipelineResult(
                posts=posts,
                collected=20,
                analyzed=20,
                next_from=None,
            )
        )
        self.assertIsNotNone(window._time_end_cursor)
        self.assertTrue(window._has_remote_more())
        self.assertGreaterEqual(window.results_view.page_count(), 2)
        requests: list[PipelineRequest] = []
        window.run_requested.connect(requests.append)
        window._on_next_page_requested()
        self.assertEqual(len(requests), 1)
        self.assertIsNone(requests[0].start_from)
        self.assertEqual(requests[0].end_time, window._time_end_cursor)

    def test_period_change_while_running_queues_restart(self) -> None:
        window = MainWindow()
        window._running = True
        window._analysis_posts = [_analyzed(1, score=0.1)]
        window.results_view.set_time_preset(TimePreset.MONTH, emit=True)
        self.assertTrue(window._pending_period_restart)

    def test_sort_by_newest_first(self) -> None:
        view = ResultsView()
        view.set_results(
            [
                _analyzed(1, score=0.9, at=datetime(2026, 9, 1, tzinfo=UTC)),
                _analyzed(2, score=0.1, at=datetime(2026, 9, 5, tzinfo=UTC)),
                _analyzed(3, score=0.8, at=datetime(2026, 9, 3, tzinfo=UTC)),
            ]
        )
        view.set_sort(ResultSort.DATE_DESC)
        self.assertEqual(
            [p.post.post_id for p in view.visible_posts()],
            [2, 3, 1],
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

    def test_keeps_same_text_from_different_posts(self) -> None:
        """Text twins are allowed; only exact VK identity is deduped."""
        view = ResultsView()
        view.set_results(
            [
                _analyzed(1, score=0.9, text="Один и тот же текст"),
                _analyzed(2, score=0.1, text="один и тот же   текст"),
                _analyzed(3, score=0.8, text="Другой текст"),
            ]
        )
        self.assertEqual(len(view.posts), 3)
        # Same owner/post_id wins once even if text differs.
        view.append_results([_analyzed(1, score=0.5, text="другая редакция")])
        self.assertEqual(len(view.posts), 3)
        self.assertEqual(
            [p.post.post_id for p in view.posts],
            [1, 2, 3],
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
        self.assertEqual(card._post_url, "https://vk.com/wall-1_1")
        self.assertTrue(card._open_post_button.isEnabled())
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
