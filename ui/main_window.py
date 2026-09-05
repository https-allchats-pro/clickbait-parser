from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
from domain.posts import post_text_key
from domain.dataset import DatasetLabel
from domain.scoring import DEFAULT_SCORING_CONFIG
from ui.theme import SP_4, SP_8, SP_12, SP_16, SP_24, get_current_theme, toggle_theme
from ui.widgets.ml_panel import MLModelPanel
from ui.widgets.model_insights_view import ModelInsightsView
from ui.widgets.results_view import ResultFilter, ResultsView

# Fixed page size for analysis + infinite scroll load-more.
PAGE_SIZE = 20


class MainWindow(QMainWindow):
    """Presentation shell: inputs, progress, results. No VK/SQLite/pipeline logic."""

    run_requested = pyqtSignal(object)
    ml_train_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("clickbait-parser")
        self.resize(980, 760)
        self.setMinimumSize(900, 650)

        self._query_input = QLineEdit()
        self._query_input.setPlaceholderText("искать продолжение, новости…")

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

        search_label = QLabel("Search")
        search_label.setObjectName("sectionLabel")

        stats_col = QVBoxLayout()
        stats_col.setSpacing(SP_4)
        stats_col.addWidget(self._stats_label)
        stats_col.addWidget(self._labeled_stats_label)

        search_row = QHBoxLayout()
        search_row.setSpacing(SP_12)
        search_col = QVBoxLayout()
        search_col.setSpacing(SP_4)
        search_col.addWidget(search_label)
        search_col.addWidget(self._query_input)
        search_row.addLayout(search_col, stretch=1)
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
        self._seen_texts: set[str] = set()
        self._page_offset: int = 0
        self._pending_append: bool = False
        self._session_query: str | None = None
        self._running: bool = False
        self._feed_exhausted: bool = False
        self._last_append_added: int = 0
        self._empty_scan_rounds: int = 0
        self._analysis_posts: list = []
        self._analysis_labels: dict[int, DatasetLabel] = {}
        self._showing_labeled_library: bool = False
        self._sync_load_more()
        self._results.label_requested.connect(self._on_label_requested)
        self._results.filter_changed.connect(self._on_filter_changed)
        self._results.scoring_mode_changed.connect(self._on_scoring_mode_changed)
        self._results.load_more_requested.connect(self._on_load_more_requested)
        self._results.run_requested.connect(self._on_run_clicked)
        self._results.min_views_changed.connect(self._on_min_views_changed)
        self._results.set_scoring_config(DEFAULT_SCORING_CONFIG)

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
        """True when infinite scroll may request another page."""
        return self._can_load_more()

    def build_request(
        self,
        *,
        start_from: str | None = None,
        exclude_texts: frozenset[str] | None = None,
    ) -> PipelineRequest:
        query = self._query_input.text().strip() or None
        return PipelineRequest(
            limit=PAGE_SIZE,
            query=query,
            start_from=start_from,
            exclude_texts=exclude_texts or frozenset(),
            min_views=self._results.current_min_views(),
        )

    def set_running(self, running: bool, *, soft: bool = False) -> None:
        """Mark pipeline busy.

        ``soft=True`` is used for infinite-scroll / min-views fill: keep the feed
        interactive and only gate new Analyse / load-more requests.
        """
        self._running = bool(running)
        self._retry_button.setEnabled(not running)
        if not running:
            self._query_input.setEnabled(True)
            self._results.set_run_busy(False, text="Анализ")
            # Keep the searching spinner visible while min-views autofill continues.
            keep_searching = self._should_autofill_min_views()
            if keep_searching:
                min_views = self._results.current_min_views()
                self._results.set_loading_more(
                    True,
                    hint=f"Ищем посты с ≥{min_views} просмотрами…",
                )
            else:
                self._results.set_loading_more(False)
            self._sync_load_more()
            delay_ms = self._autofill_delay_ms()
            QTimer.singleShot(delay_ms, self._maybe_autofill_min_views)
            return

        if soft:
            self._query_input.setEnabled(True)
            min_views = self._results.current_min_views()
            if min_views > 0:
                self._results.set_run_busy(True, text="Поиск...")
                self._results.set_loading_more(
                    True,
                    hint=f"Ищем посты с ≥{min_views} просмотрами…",
                )
            else:
                self._results.set_run_busy(True, text="Подгрузка...")
        else:
            self._query_input.setEnabled(False)
            self._results.set_run_busy(True, text="Анализируется...")
            self.clear_error()
        self._sync_load_more()

    def apply_progress(self, progress: PipelineProgress) -> None:
        """Progress UI removed — kept as a no-op for the pipeline controller."""
        _ = progress

    def show_result(self, result: PipelineResult) -> None:
        appending = self._pending_append
        self._pending_append = False
        self._showing_labeled_library = False
        added_count = 0

        if appending:
            before_count = len(self._results.posts)
            # Keep spinner visible while cards are appended, then hide.
            self._results.append_results(result.posts)
            self._results.set_loading_more(False)
            posts = self._results.posts
            added = posts[before_count:]
            added_count = len(added)
            self._analysis_posts = list(posts)
            self._load_labels_for_posts(added, merge=True)
            self._analysis_labels = dict(self._results._human_labels)
        else:
            self._results.set_loading_more(False)
            self._results.set_feed_exhausted(False)
            self._feed_exhausted = False
            self._results.set_results(result.posts)
            posts = self._results.posts
            added_count = len(posts)
            self._analysis_posts = list(posts)
            self._load_labels_for_posts(posts)
            self._analysis_labels = dict(self._results._human_labels)

        self._refresh_result_stats()

        for item in self._results.posts:
            key = post_text_key(item.post.text)
            if key:
                self._seen_texts.add(key)

        self._next_from = result.next_from
        self._page_offset = len(self._results.posts)

        # Exhaust only when VK has no further cursor — empty rounds with a
        # cursor must keep searching (min-views can skip many pages).
        if not self._next_from:
            self._feed_exhausted = True
            self._results.set_feed_exhausted(True)
        else:
            self._feed_exhausted = False
            self._results.set_feed_exhausted(False)

        self._last_append_added = added_count
        if added_count == 0 and self._results.current_min_views() > 0:
            self._empty_scan_rounds += 1
        else:
            self._empty_scan_rounds = 0
        self._sync_load_more()
        self.clear_error()

    def show_error(self, message: str) -> None:
        self._pending_append = False
        self._results.set_loading_more(False)
        self._error_detail.setText(message or "Unknown error")
        self._error_panel.show()
        self._sync_load_more()

    def clear_error(self) -> None:
        self._error_panel.hide()
        self._error_detail.clear()

    def _refresh_result_stats(self) -> None:
        # With min-views, stats follow what the user actually sees.
        posts = (
            self._results.visible_posts()
            if self._results.current_min_views() > 0
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

    def _on_min_views_changed(self, value: int) -> None:
        self._refresh_result_stats()
        # A previous "exhausted" flag was for another threshold / empty page.
        # If VK still has a cursor, reopen pagination and fill the visible page.
        if self._next_from is not None:
            self._feed_exhausted = False
            self._results.set_feed_exhausted(False)
        self._results.reset_near_bottom_gate()
        self._sync_load_more()
        if self._running:
            return
        # Defer past ResultsView._render so load-more isn't racing the rebuild.
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
        self._sync_load_more()

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
        self._sync_load_more()

    def _restore_analysis_results(self) -> None:
        self._showing_labeled_library = False
        self._results.set_results(self._analysis_posts)
        self._results.set_human_labels(self._analysis_labels)
        self._refresh_result_stats()
        self._refresh_label_stats()
        self._sync_load_more()

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

    def _can_load_more(self) -> bool:
        return (
            not self._running
            and not self._pending_append
            and not self._feed_exhausted
            and not self._showing_labeled_library
            and bool(self._analysis_posts)
            and self._next_from is not None
        )

    def _should_autofill_min_views(self) -> bool:
        """Keep fetching until we have a full visible page under min-views."""
        if self._results.current_min_views() <= 0:
            return False
        if not self._can_load_more():
            return False
        return len(self._results.visible_posts()) < PAGE_SIZE

    def _autofill_delay_ms(self) -> int:
        """Pause before the next min-views scan; grows after empty rounds."""
        if self._results.current_min_views() <= 0:
            return 0
        if not self._should_autofill_min_views():
            return 0
        # Empty worker rounds (no new matching posts) → longer pause.
        base = 150
        extra = min(2_500, 350 * max(0, self._empty_scan_rounds))
        return base + extra

    def _maybe_autofill_min_views(self) -> None:
        if not self._should_autofill_min_views():
            # Don't leave a stuck spinner that blocks scroll load-more.
            if not self._running and not self._pending_append:
                self._results.set_loading_more(False)
                self._sync_load_more()
            return
        self._on_load_more_requested()

    def _min_views_fill_limit(self) -> int:
        """How many matching posts we still need for a full visible page."""
        visible = len(self._results.visible_posts())
        return max(1, PAGE_SIZE - visible)

    def _sync_load_more(self) -> None:
        self._results.set_load_more_enabled(self._can_load_more())

    def _reset_pagination(self) -> None:
        self._next_from = None
        self._seen_texts = set()
        self._page_offset = 0
        self._pending_append = False
        self._session_query = None
        self._feed_exhausted = False
        self._last_append_added = 0
        self._empty_scan_rounds = 0
        self._results.set_feed_exhausted(False)
        self._sync_load_more()

    def _emit_request(self, request: PipelineRequest) -> None:
        self._session_query = request.query
        self.run_requested.emit(request)

    def _on_run_clicked(self) -> None:
        try:
            self._analysis_posts = []
            self._reset_pagination()
            self._pending_append = False
            request = self.build_request()
        except ValueError as exc:
            QMessageBox.warning(self, "Некорректный ввод", str(exc))
            return
        self._results.set_load_more_enabled(False)
        if request.min_views > 0:
            self._results.set_loading_more(
                True,
                hint=f"Ищем посты с ≥{request.min_views} просмотрами…",
            )
        self._emit_request(request)

    def _on_load_more_requested(self) -> None:
        if not self._can_load_more():
            # Short filtered lists can't scroll away from the bottom to reset the
            # latch — re-enable so the next tick / scroll can retry.
            self._results.reset_near_bottom_gate()
            self._sync_load_more()
            return
        try:
            self._pending_append = True
            query = self._session_query
            if query is None:
                query = self._query_input.text().strip() or None
            min_views = self._results.current_min_views()
            visible = len(self._results.visible_posts())
            if min_views > 0 and visible < PAGE_SIZE:
                limit = max(1, PAGE_SIZE - visible)
            else:
                limit = PAGE_SIZE
            request = PipelineRequest(
                limit=limit,
                query=query,
                start_from=self._next_from,
                exclude_texts=frozenset(self._seen_texts),
                min_views=min_views,
            )
        except ValueError as exc:
            self._pending_append = False
            self._results.reset_near_bottom_gate()
            self._sync_load_more()
            QMessageBox.warning(self, "Некорректный ввод", str(exc))
            return
        self._results.set_load_more_enabled(False)
        if min_views > 0:
            self._results.set_loading_more(
                True,
                hint=f"Ищем посты с ≥{min_views} просмотрами…",
            )
        else:
            self._results.set_loading_more(True)
        self._emit_request(request)
