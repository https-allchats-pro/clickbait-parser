from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.ml.feature_insights import ModelInsightsService
from domain.ml import ModelInfo
from domain.pipeline import PipelineProgress, PipelineRequest, PipelineResult
from domain.dataset import DatasetLabel
from domain.scoring import DEFAULT_SCORING_CONFIG
from ui.theme import SP_4, SP_8, SP_12, SP_16, SP_24, get_current_theme, toggle_theme
from ui.widgets.ml_panel import MLModelPanel
from ui.widgets.model_insights_view import ModelInsightsView
from ui.widgets.results_view import ResultFilter, ResultsView
from ui.widgets.search_terms import SearchTermsBar

# Default page size; UI spinbox can change it at runtime.
DEFAULT_PAGE_SIZE = 20


class MainWindow(QMainWindow):
    """Presentation shell: inputs, progress, results. No VK/SQLite/pipeline logic."""

    run_requested = pyqtSignal(object)
    ml_train_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("clickbait-parser")
        self.resize(980, 760)
        self.setMinimumSize(900, 650)

        self._search = SearchTermsBar()
        self._query_input = self._search.input

        self._stats_label = QLabel("0 posts · 0 clickbait · 0 normal")
        self._stats_label.setObjectName("statusFooter")
        self._stats_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        self._labeled_stats_label = QLabel("labeled 0")
        self._labeled_stats_label.setObjectName("statusFooter")
        self._labeled_stats_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._labeled_stats_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._labeled_stats_label.setToolTip("Показать все размеченные посты")
        self._labeled_stats_label.mousePressEvent = (  # type: ignore[method-assign]
            lambda _event: self._show_labeled_library()
        )

        stats_col = QVBoxLayout()
        stats_col.setSpacing(SP_4)
        stats_col.addWidget(self._stats_label)
        stats_col.addWidget(self._labeled_stats_label)

        search_row = QHBoxLayout()
        search_row.setSpacing(SP_12)
        search_row.addWidget(self._search, stretch=1)
        search_row.addLayout(stats_col)

        form = QVBoxLayout()
        form.setSpacing(SP_12)
        form.addLayout(search_row)

        toolbar = QFrame()
        toolbar.setObjectName("panel")
        toolbar_layout = QVBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(SP_16, SP_16, SP_16, SP_16)
        toolbar_layout.setSpacing(SP_8)
        toolbar_layout.addLayout(form)

        self._ml_panel = MLModelPanel()
        self._ml_panel.train_requested.connect(self.ml_train_requested.emit)

        self._insights = ModelInsightsView()
        self._insights.train_requested.connect(self.ml_train_requested.emit)

        self._error_title = QLabel("Не удалось выполнить анализ")
        self._error_title.setObjectName("errorTitle")
        self._error_detail = QLabel()
        self._error_detail.setObjectName("errorDetail")
        self._error_detail.setWordWrap(True)
        self._retry_button = QPushButton("Попробовать снова")
        self._retry_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._retry_button.clicked.connect(self._on_run_clicked)

        error_inner = QVBoxLayout()
        error_inner.setSpacing(SP_8)
        error_inner.addWidget(self._error_title)
        error_inner.addWidget(self._error_detail)
        error_inner.addWidget(self._retry_button, alignment=Qt.AlignmentFlag.AlignLeft)

        self._error_panel = QFrame()
        self._error_panel.setObjectName("errorPanel")
        self._error_panel.setLayout(error_inner)
        self._error_panel.hide()

        self._results = ResultsView()
        self._results.setMinimumHeight(160)

        analysis_root = QVBoxLayout()
        analysis_root.setContentsMargins(0, 0, 0, 0)
        analysis_root.setSpacing(SP_16)
        analysis_root.addWidget(toolbar)
        analysis_root.addWidget(self._error_panel)
        analysis_root.addWidget(self._results, stretch=1)
        analysis_page = QWidget()
        analysis_page.setLayout(analysis_root)

        model_root = QVBoxLayout()
        model_root.setContentsMargins(0, 0, 0, 0)
        model_root.setSpacing(SP_16)
        model_root.addWidget(self._ml_panel)
        model_root.addStretch(1)
        model_page = QWidget()
        model_page.setLayout(model_root)

        self._tabs = QTabWidget()
        self._tabs.addTab(analysis_page, "Clickbait")
        self._tabs.addTab(model_page, "Model")
        self._tabs.addTab(self._insights, "Model Insights")

        self._theme_button = QPushButton()
        self._theme_button.setObjectName("iconButton")
        self._theme_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_button.setFixedWidth(88)
        self._theme_button.clicked.connect(self._on_theme_toggled)
        self._sync_theme_button()
        self._tabs.setCornerWidget(
            self._theme_button, Qt.Corner.TopRightCorner
        )

        root = QVBoxLayout()
        root.setContentsMargins(SP_24, SP_24, SP_24, SP_24)
        root.setSpacing(SP_16)
        root.addWidget(self._tabs, stretch=1)

        container = QWidget()
        container.setLayout(root)
        self.setCentralWidget(container)

        self._controller: object | None = None
        self._ml_controller: object | None = None
        self._dataset: object | None = None
        self._ml: object | None = None
        self._next_from: str | None = None
        # Frozen VK time window for the current Analyse session (must stay fixed
        # across start_from pages — drifting end_time breaks the cursor).
        self._session_start_time: int | None = None
        self._session_end_time: int | None = None
        # When VK omits next_from on a wide window, continue by sliding end_time.
        self._time_end_cursor: int | None = None
        self._pending_period_restart: bool = False
        self._page_offset: int = 0
        self._pending_append: bool = False
        self._session_query: str | None = None
        self._session_queries: list[str] = []
        self._query_cursors: dict[str, str | None] = {}
        self._query_step_queue: list[str] = []
        self._active_query: str | None = None
        self._running: bool = False
        self._feed_exhausted: bool = False
        self._last_append_added: int = 0
        self._empty_scan_rounds: int = 0
        self._empty_page_retries: int = 0
        self._analysis_posts: list = []
        self._analysis_labels: dict[int, DatasetLabel] = {}
        self._showing_labeled_library: bool = False
        self._advance_after_fetch: bool = False
        self._pending_target_page: int | None = None
        self._sync_pager()
        self._results.label_requested.connect(self._on_label_requested)
        self._results.filter_changed.connect(self._on_filter_changed)
        self._results.scoring_mode_changed.connect(self._on_scoring_mode_changed)
        self._results.prev_page_requested.connect(self._on_prev_page_requested)
        self._results.next_page_requested.connect(self._on_next_page_requested)
        self._results.page_requested.connect(self._on_page_requested)
        self._results.page_size_changed.connect(self._on_page_size_changed)
        self._results.run_requested.connect(self._on_run_clicked)
        self._results.min_views_changed.connect(self._on_min_views_changed)
        self._results.time_window_changed.connect(self._on_time_window_changed)
        self._results.set_scoring_config(DEFAULT_SCORING_CONFIG)
        self._results.set_page_size(DEFAULT_PAGE_SIZE)

    @property
    def _run_button(self) -> QPushButton:
        """Analyse control (empty-state or results header)."""
        if self._results._empty_run_button.isVisible():
            return self._results._empty_run_button
        return self._results._header_run_button

    def _sync_theme_button(self) -> None:
        if get_current_theme() == "light":
            self._theme_button.setText("Тёмная")
            self._theme_button.setToolTip("Переключить на тёмную тему")
        else:
            self._theme_button.setText("Светлая")
            self._theme_button.setToolTip("Переключить на светлую тему")

    def _on_theme_toggled(self) -> None:
        app = QApplication.instance()
        if app is None:
            return
        toggle_theme(app)
        self._sync_theme_button()

    def set_controller(self, controller: object) -> None:
        """Keep a strong reference so the controller is not garbage-collected."""
        self._controller = controller

    def set_ml_controller(self, controller: object) -> None:
        """Keep a strong reference so the ML train controller is not GC'd."""
        self._ml_controller = controller

    def set_dataset_service(self, service: object) -> None:
        """Own SQLite DatasetService on the GUI thread for human labeling."""
        self._dataset = service
        self._refresh_label_stats()
        self.refresh_ml_panel()

    def set_ml_service(self, service: object) -> None:
        """Own SQLite MLTrainingService on the GUI thread for model status."""
        self._ml = service
        store = getattr(service, "store", None)
        if store is not None:
            self._insights.set_service(ModelInsightsService(store))
        else:
            self._insights.set_service(None)
        ready = bool(store is not None and store.exists())
        self._results.set_ml_ready(ready, apply_default_mode=True)
        self.refresh_ml_panel()

    def refresh_ml_panel(self) -> None:
        service = self._ml
        dataset = self._dataset
        clickbait = normal = dataset_total = 0
        if dataset is not None:
            stats = dataset.get_dataset_stats()  # type: ignore[attr-defined]
            clickbait = int(stats.by_label[DatasetLabel.CLICKBAIT])
            normal = int(stats.by_label[DatasetLabel.NORMAL])
            borderline = int(stats.by_label[DatasetLabel.BORDERLINE])
            dataset_total = clickbait + normal + borderline

        if service is None:
            self._ml_panel.show_not_trained(dataset_total=dataset_total)
            self._insights.refresh()
            self._results.set_ml_ready(False)
            return
        info = service.get_model_info()  # type: ignore[attr-defined]
        if info is None:
            self._ml_panel.show_not_trained(
                labeled_binary=clickbait + normal,
                dataset_total=dataset_total,
            )
            ready = False
        else:
            new_labels = int(service.new_labels_since_train())  # type: ignore[attr-defined]
            self._ml_panel.show_model_info(
                info,
                new_labels=new_labels,
                dataset_total=dataset_total,
                clickbait=clickbait,
                normal=normal,
            )
            ready = True
        self._results.set_ml_ready(ready)
        self._insights.refresh()

    def set_ml_training(self, training: bool) -> None:
        self._ml_panel.set_training(training)
        self._insights.set_training(training)

    def show_ml_train_success(self, info: ModelInfo) -> None:
        self.refresh_ml_panel()
        self._ml_panel.show_train_success(info)
        self._results.set_ml_ready(True, apply_default_mode=True)
        self._refresh_ml_scores_on_posts()
        self._insights.refresh()

    def _refresh_ml_scores_on_posts(self) -> None:
        """Re-score currently loaded posts with the freshly trained model."""
        service = self._ml
        if service is None:
            return
        try:
            predictor = service.make_predictor()  # type: ignore[attr-defined]
            if not predictor.is_ready():
                return
            predictor.reload()
        except Exception:
            return

        scores: dict[int, float | None] = {}
        for item in list(self._results.posts) + list(self._analysis_posts):
            post_id = item.post.id
            if post_id is None or post_id in scores:
                continue
            try:
                scores[post_id] = float(
                    predictor.predict_proba_clickbait(item.post.text or "")
                )
            except Exception:
                scores[post_id] = None

        if not scores:
            return
        self._results.update_ml_scores(scores)
        # Keep analysis cache in sync for restore-from-library.
        refreshed: list = []
        for item in self._analysis_posts:
            post_id = item.post.id
            if post_id is not None and post_id in scores:
                refreshed.append(
                    type(item)(
                        post=item.post,
                        analysis=item.analysis,
                        ml_score=scores[post_id],
                    )
                )
            else:
                refreshed.append(item)
        self._analysis_posts = refreshed
        self._refresh_result_stats()

    @property
    def results_view(self) -> ResultsView:
        return self._results

    @property
    def next_page_enabled(self) -> bool:
        """True when Next can advance locally or fetch another VK page."""
        return self._results.can_go_next_local() or self._can_fetch_more()

    def _page_limit(self) -> int:
        return max(1, self._results.page_size())

    def build_request(
        self,
        *,
        start_from: str | None = None,
        exclude_texts: frozenset[str] | None = None,
        query: str | None = None,
        limit: int | None = None,
        target_page: int | None = None,
        append: bool = False,
        end_time: int | None = None,
    ) -> PipelineRequest:
        score_label = self._score_label_for_filter()
        config = self._results.current_scoring_config()
        start_time = self._session_start_time
        resolved_end = end_time if end_time is not None else self._session_end_time
        if start_time is None or resolved_end is None:
            start_time, resolved_end = self._results.current_time_window()
        return PipelineRequest(
            limit=max(1, int(limit) if limit is not None else self._page_limit()),
            query=query,
            start_from=start_from,
            exclude_texts=exclude_texts or frozenset(),
            min_views=self._results.current_min_views(),
            start_time=start_time,
            end_time=resolved_end,
            score_label=score_label,
            scoring_mode=self._results.current_scoring_mode().value,
            scoring_threshold=float(config.threshold),
            scoring_rules_weight=float(config.rules_weight),
            scoring_ml_weight=float(config.ml_weight),
            append=append,
            target_page=target_page,
        )

    def _score_label_for_filter(self) -> str | None:
        filt = self._results.current_filter()
        if filt == ResultFilter.CLICKBAIT:
            return "clickbait"
        if filt == ResultFilter.NORMAL:
            return "normal"
        return None

    def _matching_posts_needed(self, *, target_page: int | None = None) -> int:
        """How many filter-matching posts the next fetch should collect."""
        page_size = self._page_limit()
        filtered = len(self._results.filtered_posts())
        if target_page is not None:
            needed_total = max(1, int(target_page)) * page_size
            return max(1, needed_total - filtered)
        return max(1, page_size - filtered)

    def _filter_loading_hint(self) -> str:
        score_label = self._score_label_for_filter()
        min_views = self._results.current_min_views()
        if score_label == "clickbait" and min_views > 0:
            return f"Ищем clickbait с ≥{min_views} просмотрами…"
        if score_label == "normal" and min_views > 0:
            return f"Ищем обычные посты с ≥{min_views} просмотрами…"
        if score_label == "clickbait":
            return "Ищем clickbait-посты…"
        if score_label == "normal":
            return "Ищем обычные посты…"
        if min_views > 0:
            return f"Ищем посты с ≥{min_views} просмотрами…"
        return "Загрузка постов…"

    def set_running(self, running: bool, *, soft: bool = False) -> None:
        """Mark pipeline busy.

        ``soft=True`` is used for page fetch / multi-query steps / min-views
        fill: keep the feed interactive and only gate new Analyse requests.
        """
        self._running = bool(running)
        self._retry_button.setEnabled(not running)
        if not running:
            self._query_input.setEnabled(True)
            self._results.set_run_busy(False, text="Анализ")
            if self._pending_period_restart:
                self._pending_period_restart = False
                self._sync_pager()
                QTimer.singleShot(0, self._on_run_clicked)
                return
            # More search words in this round → chain the next async step.
            if self._query_step_queue:
                nxt = self._query_step_queue[0]
                self._results.set_loading_more(True, hint=f"Поиск: «{nxt}»…")
                self._sync_pager()
                QTimer.singleShot(0, self._continue_query_steps)
                return
            keep_searching = self._should_autofill_min_views()
            if keep_searching:
                self._results.set_loading_more(
                    True,
                    hint=self._filter_loading_hint(),
                )
            else:
                self._results.set_loading_more(False)
            self._sync_pager()
            delay_ms = self._autofill_delay_ms()
            QTimer.singleShot(delay_ms, self._maybe_autofill_min_views)
            return

        if soft:
            self._query_input.setEnabled(True)
            if self._active_query:
                self._results.set_run_busy(True, text="Поиск...")
                self._results.set_loading_more(
                    True,
                    hint=f"Поиск: «{self._active_query}»…",
                )
            elif self._has_narrowing_filter():
                self._results.set_run_busy(True, text="Поиск...")
                self._results.set_loading_more(
                    True,
                    hint=self._filter_loading_hint(),
                )
            else:
                self._results.set_run_busy(True, text="Подгрузка...")
        else:
            self._query_input.setEnabled(False)
            self._results.set_run_busy(True, text="Анализируется...")
            self.clear_error()
        self._sync_pager()

    def apply_progress(self, progress: PipelineProgress) -> None:
        """Progress UI removed — kept as a no-op for the pipeline controller."""
        _ = progress

    def show_result(
        self,
        result: PipelineResult,
        *,
        append: bool | None = None,
        target_page: int | None = None,
    ) -> None:
        # Prefer explicit flags from the controller (tied to the in-flight request).
        # Fall back to window flags for unit tests that call show_result directly.
        # Also OR with _pending_append: a controller race used to pass append=False
        # and replace the whole feed (pagination looked stuck on page 1).
        pending = self._pending_append
        appending = pending if append is None else (bool(append) or pending)
        self._pending_append = False
        self._showing_labeled_library = False
        added_count = 0
        advance = self._advance_after_fetch
        self._advance_after_fetch = False
        if target_page is None:
            target_page = self._pending_target_page
        self._pending_target_page = None
        before_loaded = self._results.loaded_page_count() if appending else 0

        if appending:
            before_count = len(self._results.posts)
            self._results.extend_posts(result.posts)
            posts = self._results.posts
            added = posts[before_count:]
            added_count = len(added)
            self._analysis_posts = list(posts)
            self._load_labels_for_posts(added, merge=True)
            self._analysis_labels = dict(self._results._human_labels)
        else:
            self._results.set_feed_exhausted(False)
            self._feed_exhausted = False
            self._results.set_results(result.posts)
            posts = self._results.posts
            added_count = len(posts)
            self._analysis_posts = list(posts)
            self._load_labels_for_posts(posts)
            self._analysis_labels = dict(self._results._human_labels)

        self._results.set_loading_more(False)

        self._refresh_result_stats()

        self._next_from = result.next_from
        self._update_time_end_cursor(result)
        self._page_offset = len(self._results.posts)
        if self._active_query is not None:
            self._query_cursors[self._active_query] = result.next_from
            self._session_query = self._active_query
            self._active_query = None
        elif result.query_cursors:
            self._query_cursors.update(result.query_cursors)

        # Exhaust only when no VK cursor / time-watermark remains.
        if self._session_queries:
            has_more = any(self._query_cursors.get(q) for q in self._session_queries)
            has_pending_steps = bool(self._query_step_queue)
            if self._query_cursors and not has_more and not has_pending_steps:
                self._feed_exhausted = True
                self._results.set_feed_exhausted(True)
            else:
                self._feed_exhausted = False
                self._results.set_feed_exhausted(False)
        elif not self._next_from and self._time_end_cursor is None:
            self._feed_exhausted = True
            self._results.set_feed_exhausted(True)
        else:
            self._feed_exhausted = False
            self._results.set_feed_exhausted(False)

        self._last_append_added = added_count
        if added_count == 0 and (
            self._has_narrowing_filter() or appending
        ):
            self._empty_scan_rounds += 1
        else:
            self._empty_scan_rounds = 0

        want_advance = bool(advance or target_page is not None)
        desired_page = int(target_page) if target_page is not None else (
            before_loaded + 1 if want_advance else None
        )
        loaded = self._results.loaded_page_count()

        # Need another VK scan if the target filtered page is still short.
        # With score_label fill the worker usually returns enough matches in one
        # trip; this is a safety net when the feed is sparse / partially filled.
        need_more_for_page = (
            appending
            and want_advance
            and desired_page is not None
            and loaded < desired_page
            and self._has_remote_more()
        )
        if need_more_for_page:
            self._empty_page_retries += 1
            self._pending_target_page = desired_page
            self._advance_after_fetch = True
            self._results.set_loading_more(
                True,
                hint=self._filter_loading_hint(),
                clear_page=True,
            )
            self._sync_pager()
            self.clear_error()
            self._schedule_fetch_more(clear_page=True)
            return

        if added_count > 0 and not need_more_for_page:
            self._empty_page_retries = 0

        if appending and want_advance:
            if loaded <= 0:
                self._results.redraw()
            else:
                page = desired_page if desired_page is not None else loaded
                self._results.go_to_page(min(max(1, page), loaded))
        elif not appending:
            pass  # set_results already rendered page 1
        else:
            self._results.redraw()

        self._sync_pager()
        self.clear_error()

    def show_error(self, message: str) -> None:
        self._pending_append = False
        self._advance_after_fetch = False
        self._pending_target_page = None
        self._results.set_loading_more(False)
        self._error_detail.setText(message or "Unknown error")
        self._error_panel.show()
        self._sync_pager()

    def clear_error(self) -> None:
        self._error_panel.hide()
        self._error_detail.clear()

    def _refresh_result_stats(self) -> None:
        # With client filters, stats follow the filtered buffer (not only the page).
        posts = (
            self._results.filtered_posts()
            if self._has_narrowing_filter()
            else self._results.posts
        )
        clickbait = sum(
            1 for item in posts if self._results.scoring_for(item).is_clickbait
        )
        normal = len(posts) - clickbait
        self._set_stats(len(posts), clickbait, normal)

    def _on_scoring_mode_changed(self, _mode: object) -> None:
        self._refresh_result_stats()
        self._maybe_autofill_min_views()

    def _on_min_views_changed(self, _value: int) -> None:
        self._refresh_result_stats()
        self._reopen_feed_for_filters()

    def _on_time_window_changed(self) -> None:
        # Period is a VK-side filter — restart search with new start_time/end_time.
        if self._running:
            self._pending_period_restart = True
            return
        if (
            self._analysis_posts
            or self._session_queries
            or self._session_query is not None
            or bool(self._current_search_terms())
        ):
            self._on_run_clicked()

    def _reopen_feed_for_filters(self) -> None:
        # A previous "exhausted" flag was for another threshold / empty page.
        # If VK still has a cursor, reopen pagination and fill the visible page.
        has_cursor = bool(self._next_from) or any(self._query_cursors.values())
        if has_cursor:
            self._feed_exhausted = False
            self._results.set_feed_exhausted(False)
        self._results.go_to_page(1)
        self._sync_pager()
        if self._running:
            return
        QTimer.singleShot(0, self._maybe_autofill_min_views)

    def _set_stats(self, posts: int, clickbait: int, normal: int) -> None:
        self._stats_label.setText(
            f"{posts} posts · {clickbait} clickbait · {normal} normal"
        )

    def _refresh_label_stats(self) -> None:
        service = self._dataset
        if service is None:
            self._labeled_stats_label.setText("labeled 0")
            return
        stats = service.get_dataset_stats()  # type: ignore[attr-defined]
        clickbait = stats.by_label[DatasetLabel.CLICKBAIT]
        normal = stats.by_label[DatasetLabel.NORMAL]
        borderline = stats.by_label[DatasetLabel.BORDERLINE]
        total = clickbait + normal + borderline
        text = f"labeled {total}  ↑{clickbait} ↓{normal}"
        if borderline:
            text += f" ±{borderline}"
        self._labeled_stats_label.setText(text)

    def _load_labels_for_posts(self, posts: list, *, merge: bool = False) -> None:
        service = self._dataset
        if service is None:
            if not merge:
                self._results.set_human_labels({})
            self._refresh_label_stats()
            return
        ids = [item.post.id for item in posts if item.post.id is not None]
        labels = service.get_labels_for_posts(ids)  # type: ignore[attr-defined]
        if merge:
            self._results.merge_human_labels(labels)
        else:
            self._results.set_human_labels(labels)
        self._refresh_label_stats()

    def _on_filter_changed(self, value: object) -> None:
        if not isinstance(value, ResultFilter):
            try:
                value = ResultFilter(str(value))
            except ValueError:
                return
        if value == ResultFilter.LABELED:
            self._show_labeled_library()
            return
        if self._showing_labeled_library:
            self._restore_analysis_results()
            # Keep the filter the user just chose (All / Clickbait / Normal).
            self._results.set_filter(value)
        self._sync_pager()
        # Clickbait / Normal may leave the first page short — keep filling.
        self._reopen_feed_for_filters()

    def _show_labeled_library(self) -> None:
        service = self._dataset
        if service is None:
            QMessageBox.warning(
                self,
                "Разметка недоступна",
                "Сервис разметки не подключён.",
            )
            return
        try:
            posts, labels = service.list_labeled_analyzed()  # type: ignore[attr-defined]
        except Exception as exc:
            QMessageBox.warning(self, "Не удалось загрузить метки", str(exc))
            return

        self._showing_labeled_library = True
        self._results.set_results(posts)
        self._results.set_human_labels(labels)
        self._results.set_filter(ResultFilter.LABELED)
        self._refresh_ml_scores_on_posts()
        self._refresh_result_stats()
        self._refresh_label_stats()
        self._sync_pager()

    def _restore_analysis_results(self) -> None:
        self._showing_labeled_library = False
        self._results.set_results(self._analysis_posts)
        self._results.set_human_labels(self._analysis_labels)
        self._refresh_result_stats()
        self._refresh_label_stats()
        self._sync_pager()

    def _on_label_requested(self, post_id: int, label: object) -> None:
        service = self._dataset
        if service is None:
            QMessageBox.warning(
                self,
                "Разметка недоступна",
                "Сервис разметки не подключён.",
            )
            return
        if not isinstance(label, DatasetLabel):
            try:
                label = DatasetLabel(str(label))
            except ValueError:
                return

        old_id = int(post_id)
        item = self._find_analyzed_post(old_id)
        if item is None:
            QMessageBox.warning(self, "Не удалось сохранить метку", f"post {old_id} not found")
            return

        try:
            saved = service.label_analyzed_post(item, label)  # type: ignore[attr-defined]
        except Exception as exc:
            QMessageBox.warning(self, "Не удалось сохранить метку", str(exc))
            return

        new_id = saved.post.id
        assert new_id is not None
        self._results.replace_analyzed_post(old_id, saved, label=label)
        new_analysis_posts = []
        replaced = False
        for existing in self._analysis_posts:
            if existing.post.id == old_id:
                new_analysis_posts.append(saved)
                replaced = True
            else:
                new_analysis_posts.append(existing)
        if not replaced:
            new_analysis_posts.append(saved)
        self._analysis_posts = new_analysis_posts
        # Keep cache keyed by real DB id.
        self._analysis_labels.pop(old_id, None)
        self._analysis_labels[int(new_id)] = label
        self._refresh_label_stats()
        self.refresh_ml_panel()

    def _find_analyzed_post(self, post_id: int):
        for item in self._results.posts:
            if item.post.id == post_id:
                return item
        for item in self._analysis_posts:
            if item.post.id == post_id:
                return item
        return None

    def _has_remote_more(self) -> bool:
        if self._feed_exhausted or self._showing_labeled_library or not self._analysis_posts:
            return False
        if self._session_queries:
            return any(self._query_cursors.get(q) for q in self._session_queries)
        return self._next_from is not None or self._time_end_cursor is not None

    def _update_time_end_cursor(self, result: PipelineResult) -> None:
        """When VK drops next_from, slide end_time to keep paging the window."""
        if result.next_from:
            self._time_end_cursor = None
            return
        if self._session_start_time is None:
            self._time_end_cursor = None
            return
        if not result.posts:
            self._time_end_cursor = None
            return
        oldest_ts: int | None = None
        for item in result.posts:
            post_date = item.post.date
            if post_date is None:
                continue
            ts = int(post_date.timestamp())
            if oldest_ts is None or ts < oldest_ts:
                oldest_ts = ts
        if oldest_ts is None:
            self._time_end_cursor = None
            return
        candidate = oldest_ts - 1
        # Watermark must move strictly older; otherwise we would loop forever.
        if self._time_end_cursor is not None and candidate >= self._time_end_cursor:
            self._time_end_cursor = None
            return
        if candidate > int(self._session_start_time):
            self._time_end_cursor = candidate
        else:
            self._time_end_cursor = None

    def _can_fetch_more(self) -> bool:
        if self._running or self._pending_append or self._query_step_queue:
            return False
        return self._has_remote_more()

    def _can_load_more(self) -> bool:
        """Backward-compatible alias used by tests."""
        return self._can_fetch_more()

    def _has_narrowing_filter(self) -> bool:
        """True when the visible list is narrower than the raw VK buffer."""
        filt = self._results.current_filter()
        return (
            filt in {ResultFilter.CLICKBAIT, ResultFilter.NORMAL}
            or self._results.current_min_views() > 0
        )

    def _should_autofill_min_views(self) -> bool:
        """Keep fetching until the filtered buffer fills at least one page."""
        if not self._has_narrowing_filter():
            return False
        if self._query_step_queue:
            return False
        if self._showing_labeled_library:
            return False
        if not self._can_fetch_more():
            return False
        return len(self._results.filtered_posts()) < self._page_limit()

    def _autofill_delay_ms(self) -> int:
        """Pause before the next filter fill scan; grows after empty rounds."""
        if not self._has_narrowing_filter():
            return 0
        if not self._should_autofill_min_views():
            return 0
        base = 150
        extra = min(2_500, 350 * max(0, self._empty_scan_rounds))
        return base + extra

    def _maybe_autofill_min_views(self) -> None:
        if not self._should_autofill_min_views():
            if not self._running and not self._pending_append and not self._query_step_queue:
                self._results.set_loading_more(False)
                self._sync_pager()
            return
        self._fetch_more_page()

    def _min_views_fill_limit(self) -> int:
        """How many matching posts we still need for a full page."""
        filtered = len(self._results.filtered_posts())
        return max(1, self._page_limit() - filtered)

    def _sync_pager(self) -> None:
        self._results.set_pagination(
            has_more=self._has_remote_more(),
            busy=self._running or self._pending_append,
        )

    def _reset_pagination(self) -> None:
        self._next_from = None
        self._session_start_time = None
        self._session_end_time = None
        self._time_end_cursor = None
        self._page_offset = 0
        self._pending_append = False
        self._advance_after_fetch = False
        self._pending_target_page = None
        self._session_query = None
        self._session_queries = []
        self._query_cursors = {}
        self._query_step_queue = []
        self._active_query = None
        self._feed_exhausted = False
        self._last_append_added = 0
        self._empty_scan_rounds = 0
        self._empty_page_retries = 0
        self._results.set_feed_exhausted(False)
        self._sync_pager()

    def _emit_request(self, request: PipelineRequest) -> None:
        self._session_query = request.query
        self.run_requested.emit(request)

    def _current_search_terms(self) -> list[str]:
        terms = self._search.terms()
        if terms:
            return terms
        lone = self._query_input.text().strip()
        return [lone] if lone else []

    def _continue_query_steps(self) -> None:
        if self._running or self._pending_append:
            return
        if not self._query_step_queue:
            self._maybe_autofill_min_views()
            return
        self._start_next_query_step(append=True)

    def _start_next_query_step(self, *, append: bool, clear_page: bool = False) -> None:
        """Run one search word as its own async worker job."""
        while self._query_step_queue:
            query = self._query_step_queue[0]
            if query in self._query_cursors and self._query_cursors[query] is None:
                self._query_step_queue.pop(0)
                continue
            break
        else:
            self._sync_pager()
            self._maybe_autofill_min_views()
            return

        query = self._query_step_queue.pop(0)
        self._active_query = query
        self._pending_append = append
        start_from = self._query_cursors.get(query)
        target = self._pending_target_page if clear_page else None
        if self._has_narrowing_filter():
            limit = self._matching_posts_needed(target_page=target)
        else:
            limit = self._page_limit()
        request = self.build_request(
            query=query,
            start_from=start_from,
            limit=limit,
            append=append,
            target_page=target,
        )
        self._results.set_loading_more(
            True,
            hint=f"Поиск: «{query}»…",
            clear_page=clear_page,
        )
        self._sync_pager()
        self._emit_request(request)

    def _on_run_clicked(self) -> None:
        try:
            self._analysis_posts = []
            self._pending_period_restart = False
            self._reset_pagination()
            self._session_start_time, self._session_end_time = (
                self._results.current_time_window()
            )
            self._pending_append = False
            self._search.commit_input()
            terms = self._current_search_terms()
            self._session_queries = list(terms)
            self._query_cursors = {}
            if terms:
                self._query_step_queue = list(terms)
                self._start_next_query_step(append=False)
                return
            request = self.build_request(query=None)
        except ValueError as exc:
            QMessageBox.warning(self, "Некорректный ввод", str(exc))
            return
        self._sync_pager()
        if request.needs_filtered_fill:
            self._results.set_loading_more(
                True,
                hint=self._filter_loading_hint(),
            )
        self._emit_request(request)

    def _on_prev_page_requested(self) -> None:
        self._results.go_prev_page()
        self._sync_pager()

    def _on_page_requested(self, page: int) -> None:
        target = max(1, int(page))
        loaded = self._results.loaded_page_count()
        if target <= loaded:
            self._results.go_to_page(target)
            self._sync_pager()
            return
        # Provisional page beyond the buffer — fetch until that page exists.
        if self._showing_labeled_library:
            self._sync_pager()
            return
        if self._running or self._pending_append:
            self._pending_target_page = target
            self._advance_after_fetch = True
            self._schedule_fetch_more(clear_page=True)
            self._sync_pager()
            return
        if self._has_remote_more() or self._next_from or self._time_end_cursor or any(
            self._query_cursors.values()
        ):
            if self._feed_exhausted:
                self._feed_exhausted = False
                self._results.set_feed_exhausted(False)
            self._pending_target_page = target
            self._advance_after_fetch = True
            self._fetch_more_page(clear_page=True)
            return
        self._results.go_to_page(min(target, max(1, loaded)))
        self._sync_pager()

    def _on_page_size_changed(self, _size: int) -> None:
        self._results.go_to_page(1)
        self._sync_pager()
        if not self._running:
            QTimer.singleShot(0, self._maybe_autofill_min_views)

    def _on_next_page_requested(self) -> None:
        if self._results.can_go_next_local():
            self._results.go_next_page()
            self._sync_pager()
            return
        # Always try to fetch more when the user asks — even if we previously
        # marked the feed exhausted (cursor may still exist / reopen).
        if self._showing_labeled_library:
            self._sync_pager()
            return
        loaded = self._results.loaded_page_count()
        target = max(1, loaded) + 1
        if self._running or self._pending_append:
            # Remember the intent and fetch when the current job finishes.
            self._pending_target_page = target
            self._advance_after_fetch = True
            self._schedule_fetch_more(clear_page=True)
            self._sync_pager()
            return
        if self._has_remote_more() or self._next_from or self._time_end_cursor or any(
            self._query_cursors.values()
        ):
            if self._feed_exhausted:
                self._feed_exhausted = False
                self._results.set_feed_exhausted(False)
            self._pending_target_page = target
            self._advance_after_fetch = True
            self._fetch_more_page(clear_page=True)
            return
        self._sync_pager()

    def _schedule_fetch_more(self, *, clear_page: bool = False) -> None:
        """Fetch next VK page after the current worker has fully stopped."""

        def _try() -> None:
            if self._running or self._pending_append:
                QTimer.singleShot(150, _try)
                return
            self._fetch_more_page(clear_page=clear_page)

        QTimer.singleShot(150, _try)

    def _fetch_more_page(self, *, clear_page: bool = False) -> None:
        if self._running or self._pending_append:
            # Worker still winding down — retry without dropping target page.
            if self._pending_target_page is not None or self._advance_after_fetch:
                self._schedule_fetch_more(clear_page=clear_page)
                return
            self._sync_pager()
            return
        if not self._can_fetch_more():
            # Transient queue / soft-busy: keep the target and retry.
            if (
                (self._pending_target_page is not None or self._advance_after_fetch)
                and (
                    self._query_step_queue
                    or self._has_remote_more()
                    or self._next_from
                    or self._time_end_cursor
                )
            ):
                self._schedule_fetch_more(clear_page=clear_page)
                return
            self._advance_after_fetch = False
            self._pending_target_page = None
            self._sync_pager()
            return
        if self._session_queries:
            self._query_step_queue = [
                q for q in self._session_queries if self._query_cursors.get(q)
            ]
            if not self._query_step_queue:
                self._feed_exhausted = True
                self._results.set_feed_exhausted(True)
                self._advance_after_fetch = False
                self._pending_target_page = None
                self._sync_pager()
                return
            self._start_next_query_step(append=True, clear_page=clear_page)
            return
        try:
            self._pending_append = True
            query = self._session_query
            if query is None:
                query = self._query_input.text().strip() or None
            target = self._pending_target_page if clear_page else None
            if self._has_narrowing_filter():
                limit = self._matching_posts_needed(target_page=target)
            else:
                limit = self._page_limit()
            start_from = self._next_from
            end_time: int | None = None
            # VK dropped next_from — continue the frozen window via end_time slide.
            if not start_from and self._time_end_cursor is not None:
                end_time = self._time_end_cursor
            request = self.build_request(
                query=query,
                start_from=start_from,
                limit=limit,
                append=True,
                target_page=target,
                end_time=end_time,
            )
        except ValueError as exc:
            self._pending_append = False
            self._advance_after_fetch = False
            self._pending_target_page = None
            self._sync_pager()
            QMessageBox.warning(self, "Некорректный ввод", str(exc))
            return
        self._sync_pager()
        self._results.set_loading_more(
            True,
            hint=self._filter_loading_hint() if request.needs_filtered_fill else None,
            clear_page=clear_page,
        )
        self._emit_request(request)

    def _on_load_more_requested(self) -> None:
        """Alias for tests / older call sites."""
        self._fetch_more_page()
