from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from enum import Enum

from PyQt6.QtCore import QDate, QLocale, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCalendarWidget,
    QComboBox,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from domain.dataset import DatasetLabel
from domain.pipeline import AnalyzedPost
from domain.scoring import (
    DEFAULT_SCORING_CONFIG,
    PostScoring,
    ScoringConfig,
    ScoringMode,
    compute_post_scoring,
)
from ui.theme import SP_4, SP_8, SP_12, SP_16
from ui.widgets.circle_spinner import CircleSpinner
from ui.widgets.pager_bar import PagerBar
from ui.widgets.post_card import PostCard


class ResultFilter(str, Enum):
    ALL = "all"
    CLICKBAIT = "clickbait"
    NORMAL = "normal"
    LABELED = "labeled"


class ResultSort(str, Enum):
    DATE_DESC = "date_desc"  # newest → oldest (VK newsfeed.search order)
    VIEWS_DESC = "views_desc"
    VIEWS_ASC = "views_asc"
    SCORE_DESC = "score_desc"
    SCORE_ASC = "score_asc"


class TimePreset(str, Enum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    CUSTOM = "custom"


class ResultsView(QWidget):
    """Scrollable list of AnalyzedPost cards with client-side filter/sort."""

    label_requested = pyqtSignal(int, object)  # post id, DatasetLabel
    filter_changed = pyqtSignal(object)  # ResultFilter
    scoring_mode_changed = pyqtSignal(object)  # ScoringMode
    run_requested = pyqtSignal()
    min_views_changed = pyqtSignal(int)
    time_window_changed = pyqtSignal()  # VK start_time/end_time changed
    prev_page_requested = pyqtSignal()
    next_page_requested = pyqtSignal()
    page_requested = pyqtSignal(int)  # 1-based
    page_size_changed = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._posts: list[AnalyzedPost] = []
        self._human_labels: dict[int, DatasetLabel] = {}
        self._filter = ResultFilter.ALL
        self._sort = ResultSort.DATE_DESC
        self._min_views = 0
        self._time_preset = TimePreset.DAY
        self._custom_start: date | None = None
        self._custom_end: date | None = None
        self._received_results = False
        self._scoring_mode = ScoringMode.RULES
        self._scoring_config = DEFAULT_SCORING_CONFIG
        self._ml_ready = False
        self._loading_more = False
        self._feed_exhausted = False
        self._page = 1
        self._has_more = False
        self._pager_busy = False
        self._page_loading = False  # True while fetching the next pager page

        self._empty_title = QLabel("Запустите анализ")
        self._empty_title.setObjectName("emptyTitle")
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint = QLabel("Результаты появятся здесь после запуска.")
        self._empty_hint.setObjectName("emptyHint")
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint.setWordWrap(True)

        self._empty_run_button = QPushButton("Анализ")
        self._empty_run_button.setObjectName("primaryButton")
        self._empty_run_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._empty_run_button.setMinimumWidth(160)
        self._empty_run_button.clicked.connect(self.run_requested.emit)

        empty_box = QVBoxLayout()
        empty_box.setSpacing(SP_12)
        empty_box.addStretch(1)
        empty_box.addWidget(self._empty_title)
        empty_box.addWidget(self._empty_hint)
        empty_box.addWidget(self._empty_run_button, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_box.addStretch(2)
        self._empty_host = QWidget()
        self._empty_host.setLayout(empty_box)
        self._empty_title.hide()
        self._empty_hint.hide()

        self._cards_host = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_host)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(SP_12)
        self._cards_layout.addStretch(1)

        self._spinner = CircleSpinner(size=28)
        self._spinner.set_spinning(False)
        self._loading_label = QLabel("Загрузка постов…")
        self._loading_label.setObjectName("statusFooter")
        loading_row = QHBoxLayout()
        loading_row.setContentsMargins(0, SP_8, 0, SP_8)
        loading_row.setSpacing(SP_12)
        loading_row.addStretch(1)
        loading_row.addWidget(self._spinner, alignment=Qt.AlignmentFlag.AlignVCenter)
        loading_row.addWidget(self._loading_label, alignment=Qt.AlignmentFlag.AlignVCenter)
        loading_row.addStretch(1)
        self._loading_footer = QFrame()
        self._loading_footer.setObjectName("loadingFooter")
        self._loading_footer.setLayout(loading_row)
        self._loading_footer.hide()

        self._pager = PagerBar(default_size=20)
        self._pager.prev_requested.connect(self.prev_page_requested.emit)
        self._pager.next_requested.connect(self.next_page_requested.emit)
        self._pager.page_requested.connect(self.page_requested.emit)
        self._pager.page_size_changed.connect(self.page_size_changed.emit)
        self._pager.hide()

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(self._cards_host)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        mode_label = QLabel("Score mode")
        mode_label.setObjectName("sectionLabel")
        self._mode_group = QButtonGroup(self)
        self._btn_mode_rules = QPushButton("Rules")
        self._btn_mode_hybrid = QPushButton("Rules + ML")
        self._btn_mode_ml = QPushButton("ML")
        mode_row = QHBoxLayout()
        mode_row.setSpacing(SP_8)
        mode_row.addWidget(mode_label)
        for index, button in enumerate(
            (self._btn_mode_rules, self._btn_mode_hybrid, self._btn_mode_ml)
        ):
            button.setObjectName("filterButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._mode_group.addButton(button, index)
            mode_row.addWidget(button)
        self._btn_mode_rules.setChecked(True)
        self._mode_group.idClicked.connect(self._on_mode_clicked)
        mode_row.addStretch(1)
        self._mode_hint = QLabel("")
        self._mode_hint.setObjectName("statusFooter")
        mode_row.addWidget(self._mode_hint)

        self._header_run_button = QPushButton("Анализ")
        self._header_run_button.setObjectName("primaryButton")
        self._header_run_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header_run_button.clicked.connect(self.run_requested.emit)
        self._header_run_button.hide()
        mode_row.addWidget(self._header_run_button)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(SP_8)
        self._filter_group = QButtonGroup(self)
        self._btn_all = QPushButton("All")
        self._btn_clickbait = QPushButton("Clickbait")
        self._btn_normal = QPushButton("Normal")
        self._btn_labeled = QPushButton("Labeled")
        for index, button in enumerate(
            (self._btn_all, self._btn_clickbait, self._btn_normal, self._btn_labeled)
        ):
            button.setObjectName("filterButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._filter_group.addButton(button, index)
            filter_row.addWidget(button)
        self._btn_labeled.setToolTip("Показать все посты с ручной разметкой для ML")
        self._btn_all.setChecked(True)
        self._filter_group.idClicked.connect(self._on_filter_clicked)

        filter_row.addStretch(1)

        sort_label = QLabel("Сортировка")
        sort_label.setObjectName("sectionLabel")
        self._sort_combo = QComboBox()
        self._sort_combo.addItem("Сначала новые", ResultSort.DATE_DESC.value)
        self._sort_combo.addItem("Просмотры ↓", ResultSort.VIEWS_DESC.value)
        self._sort_combo.addItem("Просмотры ↑", ResultSort.VIEWS_ASC.value)
        self._sort_combo.addItem("Final % ↓", ResultSort.SCORE_DESC.value)
        self._sort_combo.addItem("Final % ↑", ResultSort.SCORE_ASC.value)
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)

        min_label = QLabel("Мин. просмотры")
        min_label.setObjectName("sectionLabel")
        self._min_views_input = QSpinBox()
        self._min_views_input.setMinimum(0)
        self._min_views_input.setMaximum(100_000_000)
        self._min_views_input.setValue(0)
        self._min_views_input.setSingleStep(100)
        self._min_views_input.setFixedWidth(110)
        self._min_views_input.setToolTip("Показывать только посты с не меньшим числом просмотров")
        self._min_views_input.valueChanged.connect(self._on_min_views_changed)

        period_label = QLabel("Период")
        period_label.setObjectName("sectionLabel")
        self._period_combo = QComboBox()
        self._period_combo.addItem("За сутки", TimePreset.DAY.value)
        self._period_combo.addItem("За неделю", TimePreset.WEEK.value)
        self._period_combo.addItem("За месяц", TimePreset.MONTH.value)
        self._period_combo.addItem("Свой период", TimePreset.CUSTOM.value)
        self._period_combo.setToolTip(
            "Окно newsfeed.search: start_time / end_time (по умолчанию — сутки)"
        )
        self._period_combo.currentIndexChanged.connect(self._on_period_changed)

        self._custom_period_host = QWidget()
        custom_row = QHBoxLayout(self._custom_period_host)
        custom_row.setContentsMargins(0, 0, 0, 0)
        custom_row.setSpacing(SP_8)
        from_lbl = QLabel("с")
        from_lbl.setObjectName("sectionLabel")
        to_lbl = QLabel("по")
        to_lbl.setObjectName("sectionLabel")
        self._period_start_input = QDateEdit()
        self._period_end_input = QDateEdit()
        for edit in (self._period_start_input, self._period_end_input):
            self._configure_russian_date_edit(edit)
        today = QDate.currentDate()
        self._period_start_input.setDate(today.addDays(-7))
        self._period_end_input.setDate(today)
        self._period_start_input.dateChanged.connect(self._on_custom_period_changed)
        self._period_end_input.dateChanged.connect(self._on_custom_period_changed)
        custom_row.addWidget(from_lbl)
        custom_row.addWidget(self._period_start_input)
        custom_row.addWidget(to_lbl)
        custom_row.addWidget(self._period_end_input)
        self._custom_period_host.hide()

        controls = QHBoxLayout()
        controls.setSpacing(SP_8)
        sort_col = QVBoxLayout()
        sort_col.setSpacing(SP_4)
        sort_col.addWidget(sort_label)
        sort_col.addWidget(self._sort_combo)
        min_col = QVBoxLayout()
        min_col.setSpacing(SP_4)
        min_col.addWidget(min_label)
        min_col.addWidget(self._min_views_input)
        period_col = QVBoxLayout()
        period_col.setSpacing(SP_4)
        period_col.addWidget(period_label)
        period_col.addWidget(self._period_combo)
        period_col.addWidget(self._custom_period_host)
        controls.addLayout(sort_col)
        controls.addLayout(min_col)
        controls.addLayout(period_col)
        controls.addStretch(1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SP_12)
        root.addLayout(mode_row)
        root.addLayout(filter_row)
        root.addLayout(controls)
        root.addWidget(self._empty_host, stretch=1)
        root.addWidget(self._scroll, stretch=1)
        root.addWidget(self._pager)
        self._scroll.hide()
        self._sync_mode_buttons()

    def set_results(self, posts: list[AnalyzedPost]) -> None:
        self._posts = self._unique_by_identity(posts)
        self._human_labels = {}
        self._received_results = True
        self._page_loading = False
        self._page = 1
        self._render()
        self._scroll_to_top()

    def extend_posts(self, posts: list[AnalyzedPost]) -> None:
        """Append to the buffer without rendering (caller decides the page)."""
        if not posts:
            return
        self._posts = self._unique_by_identity([*self._posts, *posts])
        self._received_results = True

    def append_results(self, posts: list[AnalyzedPost]) -> None:
        """Extend the in-memory buffer and redraw the current page."""
        self.extend_posts(posts)
        self._render()

    def redraw(self) -> None:
        self._render()
        self._scroll_to_top()

    def set_pagination(self, *, has_more: bool, busy: bool = False) -> None:
        self._has_more = bool(has_more)
        self._pager_busy = bool(busy)
        self._sync_pager()

    def page_size(self) -> int:
        return self._pager.page_size()

    def set_page_size(self, value: int, *, emit: bool = False) -> None:
        self._pager.set_page_size(value, emit=emit)

    def current_page(self) -> int:
        return self._page

    def page_count(self) -> int:
        """Loaded pages, plus one provisional page while remote fetch may continue."""
        loaded = self.loaded_page_count()
        if loaded <= 0:
            return 0
        # Always expose a provisional next page while VK may have more —
        # otherwise pages 1–3 look capped at 4 even when Next can go further.
        if self._has_more and not self._feed_exhausted:
            return loaded + 1
        return loaded

    def loaded_page_count(self) -> int:
        size = max(1, self.page_size())
        total_items = len(self.filtered_posts())
        if total_items <= 0:
            return 0
        return max(1, (total_items + size - 1) // size)

    def can_go_next_local(self) -> bool:
        return self._page < self.loaded_page_count()

    def go_to_page(self, page: int) -> None:
        """Open a loaded page. Remote pages are requested by MainWindow."""
        loaded = self.loaded_page_count()
        target = max(1, int(page))
        if loaded <= 0:
            self._page = 1
        else:
            self._page = min(target, loaded)
        self._render()
        self._scroll_to_top()

    def go_prev_page(self) -> None:
        if self._page > 1:
            self._page -= 1
            self._render()
            self._scroll_to_top()

    def go_next_page(self) -> None:
        if self.can_go_next_local():
            self._page += 1
            self._render()
            self._scroll_to_top()

    def set_loading_more(
        self,
        loading: bool,
        *,
        hint: str | None = None,
        clear_page: bool = False,
    ) -> None:
        """Show/hide spinner while a page is loading.

        ``clear_page=True`` replaces the current cards with a loading state
        (used when advancing the pager to a not-yet-fetched page).
        """
        was_page_loading = self._page_loading
        self._loading_more = bool(loading)
        if loading:
            self._page_loading = bool(clear_page)
        else:
            self._page_loading = False

        if hint:
            self._loading_label.setText(hint)
        elif self._min_views > 0:
            self._loading_label.setText(
                f"Ищем посты с ≥{self._min_views} просмотрами…"
            )
        else:
            self._loading_label.setText("Загрузка постов…")

        if self._loading_more:
            self._empty_host.hide()
            self._scroll.show()
            self._header_run_button.show()
            self._pager.show()
            if self._page_loading:
                self._clear_cards()
                self._cards_layout.addStretch(1)
                self._ensure_loading_footer()
                loaded = self.loaded_page_count()
                if loaded > 0:
                    self._page = loaded + 1
            else:
                self._ensure_loading_footer()
            self._loading_footer.show()
            self._spinner.set_spinning(True)
            self._scroll_to_top()
            self._sync_pager()
            return

        self._spinner.set_spinning(False)
        self._loading_footer.hide()
        self._loading_label.setText("Загрузка постов…")
        # Do not render here — MainWindow chooses the target page after fetch.
        if was_page_loading:
            self._sync_pager()
            return
        self._sync_pager()

    def _scroll_to_top(self) -> None:
        bar = self._scroll.verticalScrollBar()
        bar.setValue(0)

    def set_feed_exhausted(self, exhausted: bool) -> None:
        self._feed_exhausted = bool(exhausted)
        if exhausted:
            self._has_more = False
        self._sync_pager()

    def _sync_pager(self) -> None:
        loaded = self.loaded_page_count()
        if not self._page_loading and loaded > 0 and self._page > loaded:
            self._page = loaded
        busy = self._pager_busy or self._loading_more
        has_more = self._has_more and not self._feed_exhausted
        total = self.page_count()
        if self._page_loading and loaded > 0:
            total = max(total, self._page)
        self._pager.set_pagination(
            current=max(1, self._page),
            total=total,
            has_more=has_more,
            busy=busy,
        )

    def update_ml_scores(self, scores_by_post_id: dict[int, float | None]) -> None:
        """Refresh ML probabilities on already loaded posts (e.g. after train)."""
        updated: list[AnalyzedPost] = []
        for item in self._posts:
            post_id = item.post.id
            if post_id is not None and post_id in scores_by_post_id:
                updated.append(
                    AnalyzedPost(
                        post=item.post,
                        analysis=item.analysis,
                        ml_score=scores_by_post_id[post_id],
                    )
                )
            else:
                updated.append(item)
        self._posts = updated
        self._render()

    def set_human_labels(self, labels: dict[int, DatasetLabel]) -> None:
        self._human_labels = dict(labels)
        # Empty labels after set_results — avoid a second full rebuild (UI freeze).
        if not labels:
            return
        self._render()

    def merge_human_labels(self, labels: dict[int, DatasetLabel]) -> None:
        """Merge labels without rebuilding the whole list."""
        if not labels:
            return
        self._human_labels.update(labels)
        for index in range(self._cards_layout.count()):
            item = self._cards_layout.itemAt(index)
            widget = item.widget() if item is not None else None
            if not isinstance(widget, PostCard):
                continue
            post_id = widget._local_post_id
            if post_id is not None and post_id in labels:
                widget.set_human_label(labels[post_id])

    def update_human_label(self, post_id: int, label: DatasetLabel) -> None:
        self._human_labels[int(post_id)] = label
        for index in range(self._cards_layout.count()):
            item = self._cards_layout.itemAt(index)
            widget = item.widget() if item is not None else None
            if isinstance(widget, PostCard) and widget._local_post_id == post_id:
                widget.set_human_label(label)
                return
        self._render()

    def replace_analyzed_post(
        self,
        old_post_id: int,
        item: AnalyzedPost,
        *,
        label: DatasetLabel | None = None,
    ) -> None:
        """Swap an in-memory post (e.g. ephemeral id → real DB id) after labeling."""
        new_id = item.post.id
        updated: list[AnalyzedPost] = []
        for existing in self._posts:
            if existing.post.id == old_post_id:
                updated.append(item)
            else:
                updated.append(existing)
        self._posts = updated

        if old_post_id in self._human_labels:
            self._human_labels.pop(old_post_id, None)
        if label is not None and new_id is not None:
            self._human_labels[int(new_id)] = label

        for index in range(self._cards_layout.count()):
            layout_item = self._cards_layout.itemAt(index)
            widget = layout_item.widget() if layout_item is not None else None
            if isinstance(widget, PostCard) and widget._local_post_id == old_post_id:
                widget.set_post(
                    item,
                    mode=self._scoring_mode,
                    config=self._scoring_config,
                )
                if label is not None:
                    widget.set_human_label(label)
                elif new_id is not None and new_id in self._human_labels:
                    widget.set_human_label(self._human_labels[new_id])
                return
        self._render()

    def clear(self) -> None:
        self._posts = []
        self._human_labels = {}
        self._received_results = False
        self._render()

    def set_filter(self, value: ResultFilter) -> None:
        self._filter = value
        self._page = 1
        mapping = {
            ResultFilter.ALL: self._btn_all,
            ResultFilter.CLICKBAIT: self._btn_clickbait,
            ResultFilter.NORMAL: self._btn_normal,
            ResultFilter.LABELED: self._btn_labeled,
        }
        mapping[value].setChecked(True)
        self._render()

    def set_scoring_mode(self, mode: ScoringMode, *, emit: bool = False) -> None:
        self._scoring_mode = mode
        self._sync_mode_buttons()
        self._render()
        if emit:
            self.scoring_mode_changed.emit(mode)

    def set_scoring_config(self, config: ScoringConfig) -> None:
        self._scoring_config = config
        self._render()

    def set_ml_ready(self, ready: bool, *, apply_default_mode: bool = False) -> None:
        self._ml_ready = bool(ready)
        self._sync_mode_buttons()
        if apply_default_mode:
            from domain.scoring import default_mode_for_model

            self.set_scoring_mode(default_mode_for_model(model_ready=self._ml_ready))
        else:
            self._render()

    def scoring_for(self, item: AnalyzedPost) -> PostScoring:
        return compute_post_scoring(
            rules_score=item.rules_score,
            ml_score=item.ml_score,
            mode=self._scoring_mode,
            config=self._scoring_config,
        )

    def set_sort(self, value: ResultSort) -> None:
        self._sort = value
        index = self._sort_combo.findData(value.value)
        if index >= 0:
            self._sort_combo.setCurrentIndex(index)
        self._render()

    def set_min_views(self, value: int) -> None:
        self._min_views = max(0, int(value))
        self._min_views_input.blockSignals(True)
        self._min_views_input.setValue(self._min_views)
        self._min_views_input.blockSignals(False)
        self._render()
        self.min_views_changed.emit(self._min_views)

    def set_time_preset(self, value: TimePreset, *, emit: bool = False) -> None:
        self._time_preset = value
        index = self._period_combo.findData(value.value)
        if index >= 0:
            self._period_combo.blockSignals(True)
            self._period_combo.setCurrentIndex(index)
            self._period_combo.blockSignals(False)
        self._custom_period_host.setVisible(value == TimePreset.CUSTOM)
        if emit:
            self.time_window_changed.emit()

    def set_custom_period(self, start: date, end: date, *, emit: bool = False) -> None:
        if end < start:
            start, end = end, start
        self._custom_start = start
        self._custom_end = end
        self._period_start_input.blockSignals(True)
        self._period_end_input.blockSignals(True)
        self._period_start_input.setDate(QDate(start.year, start.month, start.day))
        self._period_end_input.setDate(QDate(end.year, end.month, end.day))
        self._period_start_input.blockSignals(False)
        self._period_end_input.blockSignals(False)
        self.set_time_preset(TimePreset.CUSTOM, emit=emit)

    def current_filter(self) -> ResultFilter:
        return self._filter

    def current_scoring_mode(self) -> ScoringMode:
        return self._scoring_mode

    def current_scoring_config(self) -> ScoringConfig:
        return self._scoring_config

    def current_sort(self) -> ResultSort:
        return self._sort

    def current_min_views(self) -> int:
        return self._min_views

    def current_time_preset(self) -> TimePreset:
        return self._time_preset

    def current_time_window(self) -> tuple[int, int]:
        """Unix ``(start_time, end_time)`` for newsfeed.search."""
        now = datetime.now().astimezone()
        end = now
        if self._time_preset == TimePreset.DAY:
            start = now - timedelta(days=1)
        elif self._time_preset == TimePreset.WEEK:
            start = now - timedelta(days=7)
        elif self._time_preset == TimePreset.MONTH:
            start = now - timedelta(days=30)
        else:
            start_day = self._custom_start or (now.date() - timedelta(days=7))
            end_day = self._custom_end or now.date()
            if end_day < start_day:
                start_day, end_day = end_day, start_day
            start = datetime(
                start_day.year, start_day.month, start_day.day, 0, 0, 0
            ).astimezone()
            end = datetime(
                end_day.year, end_day.month, end_day.day, 23, 59, 59
            ).astimezone()
        return int(start.timestamp()), int(end.timestamp())

    @property
    def posts(self) -> list[AnalyzedPost]:
        """Deduped posts currently held by the view (before filter/sort)."""
        return list(self._posts)

    def filtered_posts(self) -> list[AnalyzedPost]:
        """All posts matching the current filter/sort (full buffer)."""
        posts = [p for p in self._posts if self._passes_current_filters(p)]

        if self._sort == ResultSort.DATE_DESC:
            posts.sort(
                key=lambda p: p.post.date or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
        elif self._sort == ResultSort.VIEWS_DESC:
            posts.sort(key=lambda p: int(p.post.views or 0), reverse=True)
        elif self._sort == ResultSort.VIEWS_ASC:
            posts.sort(key=lambda p: int(p.post.views or 0))
        elif self._sort == ResultSort.SCORE_DESC:
            posts.sort(key=lambda p: float(self.scoring_for(p).final_score), reverse=True)
        elif self._sort == ResultSort.SCORE_ASC:
            posts.sort(key=lambda p: float(self.scoring_for(p).final_score))
        return posts

    def visible_posts(self) -> list[AnalyzedPost]:
        """Posts shown on the current page (after filter/sort)."""
        pool = self.filtered_posts()
        size = max(1, self.page_size())
        start = (max(1, self._page) - 1) * size
        return pool[start : start + size]

    def _passes_current_filters(self, item: AnalyzedPost) -> bool:
        if self._filter == ResultFilter.CLICKBAIT:
            if not self.scoring_for(item).is_clickbait:
                return False
        elif self._filter == ResultFilter.NORMAL:
            if self.scoring_for(item).is_clickbait:
                return False
        elif self._filter == ResultFilter.LABELED:
            if item.post.id is None or item.post.id not in self._human_labels:
                return False
        if self._min_views > 0 and int(item.post.views or 0) < self._min_views:
            return False
        return True

    @staticmethod
    def _unique_by_identity(posts: list[AnalyzedPost]) -> list[AnalyzedPost]:
        """Keep first occurrence of each VK post id; same text from different posts is OK."""
        unique: list[AnalyzedPost] = []
        seen_ids: set[tuple[str, int, int]] = set()
        seen_local: set[int] = set()
        for item in posts:
            post = item.post
            key = (post.source, int(post.owner_id), int(post.post_id))
            if key in seen_ids:
                continue
            seen_ids.add(key)
            if post.id is not None:
                local = int(post.id)
                if local in seen_local:
                    continue
                seen_local.add(local)
            unique.append(item)
        return unique

    def _sync_mode_buttons(self) -> None:
        mapping = {
            ScoringMode.RULES: self._btn_mode_rules,
            ScoringMode.RULES_ML: self._btn_mode_hybrid,
            ScoringMode.ML: self._btn_mode_ml,
        }
        mapping[self._scoring_mode].setChecked(True)
        self._btn_mode_hybrid.setEnabled(self._ml_ready)
        self._btn_mode_ml.setEnabled(self._ml_ready)
        if not self._ml_ready:
            self._mode_hint.setText("ML not trained — Rules only")
            self._btn_mode_hybrid.setToolTip("Train an ML model first")
            self._btn_mode_ml.setToolTip("Train an ML model first")
        else:
            self._mode_hint.setText("")
            self._btn_mode_hybrid.setToolTip("")
            self._btn_mode_ml.setToolTip("")

    def _on_mode_clicked(self, button_id: int) -> None:
        mapping = {
            0: ScoringMode.RULES,
            1: ScoringMode.RULES_ML,
            2: ScoringMode.ML,
        }
        mode = mapping.get(button_id, ScoringMode.RULES)
        if mode != ScoringMode.RULES and not self._ml_ready:
            self._sync_mode_buttons()
            return
        self._scoring_mode = mode
        self.scoring_mode_changed.emit(mode)
        self._render()

    def _on_filter_clicked(self, button_id: int) -> None:
        mapping = {
            0: ResultFilter.ALL,
            1: ResultFilter.CLICKBAIT,
            2: ResultFilter.NORMAL,
            3: ResultFilter.LABELED,
        }
        self._filter = mapping.get(button_id, ResultFilter.ALL)
        self._page = 1
        self.filter_changed.emit(self._filter)
        self._render()

    def _on_sort_changed(self, _index: int) -> None:
        raw = self._sort_combo.currentData()
        try:
            self._sort = ResultSort(str(raw))
        except ValueError:
            self._sort = ResultSort.DATE_DESC
        self._page = 1
        self._render()

    def _on_min_views_changed(self, value: int) -> None:
        self._min_views = max(0, int(value))
        self._page = 1
        self._render()
        self.min_views_changed.emit(self._min_views)

    @staticmethod
    def _configure_russian_date_edit(edit: QDateEdit) -> None:
        locale = QLocale(QLocale.Language.Russian, QLocale.Country.Russia)
        edit.setLocale(locale)
        edit.setCalendarPopup(True)
        edit.setDisplayFormat("dd.MM.yyyy")
        edit.setMinimumDate(QDate(2006, 1, 1))
        edit.setMaximumDate(QDate.currentDate().addDays(1))
        edit.setFixedWidth(130)
        calendar = edit.calendarWidget()
        if calendar is not None:
            calendar.setLocale(locale)
            calendar.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
            calendar.setNavigationBarVisible(True)
            calendar.setHorizontalHeaderFormat(
                QCalendarWidget.HorizontalHeaderFormat.ShortDayNames
            )
            calendar.setVerticalHeaderFormat(
                QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader
            )
            calendar.setGridVisible(True)

    def _on_period_changed(self, _index: int) -> None:
        raw = self._period_combo.currentData()
        try:
            self._time_preset = TimePreset(str(raw))
        except ValueError:
            self._time_preset = TimePreset.DAY
        self._custom_period_host.setVisible(self._time_preset == TimePreset.CUSTOM)
        if self._time_preset == TimePreset.CUSTOM:
            start_q = self._period_start_input.date()
            end_q = self._period_end_input.date()
            self._custom_start = date(start_q.year(), start_q.month(), start_q.day())
            self._custom_end = date(end_q.year(), end_q.month(), end_q.day())
        self.time_window_changed.emit()

    def _on_custom_period_changed(self, _qdate: QDate) -> None:
        if self._time_preset != TimePreset.CUSTOM:
            return
        start_q = self._period_start_input.date()
        end_q = self._period_end_input.date()
        if not start_q.isValid() or not end_q.isValid():
            return
        self._custom_start = date(start_q.year(), start_q.month(), start_q.day())
        self._custom_end = date(end_q.year(), end_q.month(), end_q.day())
        self.time_window_changed.emit()

    def _clear_cards(self) -> None:
        footer_index = self._cards_layout.indexOf(self._loading_footer)
        if footer_index >= 0:
            self._cards_layout.takeAt(footer_index)
        for index in reversed(range(self._cards_layout.count())):
            taken = self._cards_layout.takeAt(index)
            widget = taken.widget() if taken is not None else None
            if widget is not None:
                widget.deleteLater()
            del taken

    def _ensure_loading_footer(self) -> None:
        if self._cards_layout.indexOf(self._loading_footer) < 0:
            stretch_index = self._cards_layout.count()
            for index in range(self._cards_layout.count()):
                item = self._cards_layout.itemAt(index)
                if item is not None and item.spacerItem() is not None:
                    stretch_index = index
                    break
            self._cards_layout.insertWidget(stretch_index, self._loading_footer)

    def _make_post_card(self, item: AnalyzedPost) -> PostCard:
        card = PostCard()
        card.set_post(
            item,
            mode=self._scoring_mode,
            config=self._scoring_config,
        )
        local_id = item.post.id
        if local_id is not None and local_id in self._human_labels:
            card.set_human_label(self._human_labels[local_id])
        card.label_requested.connect(self.label_requested.emit)
        return card

    def set_run_busy(self, busy: bool, *, text: str | None = None) -> None:
        """Enable/disable Analyse buttons and optionally set their label."""
        enabled = not busy
        label = text if text is not None else ("Анализ" if enabled else "Анализируется...")
        for button in (self._empty_run_button, self._header_run_button):
            button.setEnabled(enabled)
            button.setText(label)

    def _show_empty(self, title: str, hint: str, *, show_run: bool = True) -> None:
        """Empty state: optional title/hint + Analyse CTA (default)."""
        if title or hint:
            self._empty_title.setText(title)
            self._empty_hint.setText(hint)
            self._empty_title.show()
            self._empty_hint.show()
        else:
            self._empty_title.hide()
            self._empty_hint.hide()
        self._empty_run_button.setVisible(show_run)
        self._header_run_button.hide()
        self._empty_host.show()
        self._scroll.hide()
        self.set_loading_more(False)
        self._sync_pager()

    def _render(self) -> None:
        keep_loading = self._loading_more
        page_loading = self._page_loading
        self._clear_cards()
        pool = self.filtered_posts()
        size = max(1, self.page_size())
        if pool and self._page > 1 and not page_loading:
            max_page = max(1, (len(pool) + size - 1) // size)
            if self._page > max_page:
                self._page = max_page
        page_items = [] if page_loading else self.visible_posts()

        if not self._received_results:
            self._show_empty("", "", show_run=True)
            self._cards_layout.addStretch(1)
            return

        if not self._posts:
            if self._filter == ResultFilter.LABELED:
                self._show_empty(
                    "Нет размеченных постов",
                    "Пометьте посты кнопками 👍 / 👎 после анализа.",
                )
            else:
                self._show_empty(
                    "Посты не найдены",
                    "Попробуйте изменить поисковый запрос.",
                )
            self._cards_layout.addStretch(1)
            return

        if page_loading:
            self._empty_host.hide()
            self._scroll.show()
            self._header_run_button.show()
            self._cards_layout.addStretch(1)
            self._ensure_loading_footer()
            self._loading_footer.show()
            self._spinner.set_spinning(True)
            self._sync_pager()
            self._scroll_to_top()
            return

        if not pool:
            if self._posts and (
                (
                    self._min_views > 0
                    or self._filter in {ResultFilter.CLICKBAIT, ResultFilter.NORMAL}
                )
                and not self._feed_exhausted
            ):
                self._empty_host.hide()
                self._scroll.show()
                self._header_run_button.show()
                self._cards_layout.addStretch(1)
                self._ensure_loading_footer()
                self._loading_footer.show()
                self._spinner.set_spinning(True)
                if self._min_views > 0:
                    self._loading_label.setText(
                        f"Ищем посты с ≥{self._min_views} просмотрами…"
                    )
                elif self._filter == ResultFilter.CLICKBAIT:
                    self._loading_label.setText("Ищем clickbait-посты…")
                else:
                    self._loading_label.setText("Ищем обычные посты…")
                self._sync_pager()
                return
            if self._filter == ResultFilter.LABELED:
                self._show_empty(
                    "Нет размеченных постов",
                    "Пометьте посты кнопками 👍 / 👎 — они появятся здесь.",
                )
            else:
                self._show_empty(
                    "Нет постов для выбранных фильтров",
                    "Измените All / Clickbait / Normal / Labeled или мин. просмотры.",
                )
            self._cards_layout.addStretch(1)
            return

        self._empty_host.hide()
        self._scroll.show()
        self._header_run_button.show()
        for item in page_items:
            self._cards_layout.addWidget(self._make_post_card(item))

        self._cards_layout.addStretch(1)
        self._ensure_loading_footer()
        if keep_loading:
            self._loading_footer.show()
            self._spinner.set_spinning(True)
        else:
            self._loading_footer.hide()
            self._spinner.set_spinning(False)
        self._sync_pager()
