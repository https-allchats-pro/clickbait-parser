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
from domain.posts import CatalogPost, SOURCE_VK_CATALOG
from ui.formatters import format_post_date, format_reason, format_score_percent, human_state
from ui.main_window import MainWindow
from ui.profile_dialog import ProfileSelectDialog, format_profile_label
from ui.widgets.post_card import PostCard
from ui.widgets.results_view import ResultFilter, ResultsView
from app.auth.models import VKProfile
from ui.theme import apply_theme

_APP = QApplication.instance()
if _APP is None:
    _APP = QApplication(["clickbait-parser-tests"])
apply_theme(_APP)


def _post(local_id: int, text: str = "text") -> CatalogPost:
    return CatalogPost(
        source=SOURCE_VK_CATALOG,
        owner_id=-1,
        post_id=local_id,
        text=text,
        date=datetime.fromtimestamp(1_700_000_000, tz=UTC),
        id=local_id,
    )


def _analyzed(local_id: int, *, score: float, text: str = "text") -> AnalyzedPost:
    return AnalyzedPost(
        post=_post(local_id, text=text),
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
        window._limit_input.setValue(42)
        request = window.build_request()
        self.assertEqual(request.limit, 42)
        self.assertEqual(request.query, "новости")

    def test_empty_query_becomes_none(self) -> None:
        window = MainWindow()
        window._query_input.setText("   ")
        window._limit_input.setValue(10)
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

        window.show_result(
            PipelineResult(
                posts=[_analyzed(1, score=0.9), _analyzed(2, score=0.1)],
                collected=2,
                analyzed=2,
            )
        )
        self.assertEqual(len(window.results_view.visible_posts()), 2)
        self.assertEqual(window._stat_posts._value_label.text(), "2")
        self.assertEqual(window._stat_clickbait._value_label.text(), "1")
        self.assertEqual(window._stat_normal._value_label.text(), "1")

    def test_show_error(self) -> None:
        window = MainWindow()
        window.show_error("network timeout")
        self.assertFalse(window._error_panel.isHidden())
        self.assertIn("Ошибка", window._progress_title.text())
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


class FormattersTests(unittest.TestCase):
    def test_score_and_reason_and_date(self) -> None:
        self.assertEqual(format_score_percent(0.82), "82%")
        self.assertEqual(format_reason("continuation_bait"), "Continuation bait")
        when = format_post_date(datetime(2026, 9, 4, 1, 1, tzinfo=UTC))
        self.assertIn("сент.", when)
        self.assertIn("2026", when)
        self.assertEqual(human_state(PipelineState.ANALYZING), "Анализ постов")


class PostCardTests(unittest.TestCase):
    def test_renders_percent_and_copies_text(self) -> None:
        card = PostCard()
        item = _analyzed(1, score=0.82, text="полный текст поста")
        card.set_post(item)
        self.assertEqual(card._score.text(), "82%")
        self.assertEqual(card._prediction.text(), "CLICKBAIT")
        card._on_copy()
        self.assertEqual(QApplication.clipboard().text(), "полный текст поста")
        self.assertEqual(card._copy_button.toolTip(), "Copied")


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
