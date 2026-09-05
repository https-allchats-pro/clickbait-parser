from __future__ import annotations

from enum import Enum

from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
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
from domain.posts import post_text_key
from domain.scoring import (
    DEFAULT_SCORING_CONFIG,
    PostScoring,
    ScoringConfig,
    ScoringMode,
    compute_post_scoring,
)
from ui.theme import SP_4, SP_8, SP_12, SP_16
from ui.widgets.circle_spinner import CircleSpinner
from ui.widgets.post_card import PostCard


class ResultFilter(str, Enum):
    ALL = "all"
    CLICKBAIT = "clickbait"
    NORMAL = "normal"
    LABELED = "labeled"


class ResultSort(str, Enum):
    DEFAULT = "default"
    VIEWS_DESC = "views_desc"
    VIEWS_ASC = "views_asc"
    SCORE_DESC = "score_desc"
    SCORE_ASC = "score_asc"


_NEAR_BOTTOM_PX = 240


class ResultsView(QWidget):
    """Scrollable list of AnalyzedPost cards with client-side filter/sort."""

    label_requested = pyqtSignal(int, object)  # post id, DatasetLabel
    filter_changed = pyqtSignal(object)  # ResultFilter
    scoring_mode_changed = pyqtSignal(object)  # ScoringMode
    load_more_requested = pyqtSignal()
    run_requested = pyqtSignal()
    min_views_changed = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._posts: list[AnalyzedPost] = []
        self._human_labels: dict[int, DatasetLabel] = {}
        self._filter = ResultFilter.ALL
        self._sort = ResultSort.DEFAULT
        self._min_views = 0
        self._received_results = False
        self._scoring_mode = ScoringMode.RULES
        self._scoring_config = DEFAULT_SCORING_CONFIG
        self._ml_ready = False
        self._load_more_enabled = False
        self._loading_more = False
        self._near_bottom_emitted = False
        self._feed_exhausted = False

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
        loading_row.setContentsMargins(0, SP_8, 0, SP_16)
        loading_row.setSpacing(SP_12)
        loading_row.addStretch(1)
        loading_row.addWidget(self._spinner, alignment=Qt.AlignmentFlag.AlignVCenter)
        loading_row.addWidget(self._loading_label, alignment=Qt.AlignmentFlag.AlignVCenter)
        loading_row.addStretch(1)
        self._loading_footer = QFrame()
        self._loading_footer.setObjectName("loadingFooter")
        self._loading_footer.setLayout(loading_row)
        self._loading_footer.hide()

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(self._cards_host)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.viewport().installEventFilter(self)
        scrollbar = self._scroll.verticalScrollBar()
        scrollbar.valueChanged.connect(self._on_scroll_changed)
        scrollbar.rangeChanged.connect(self._on_scroll_range_changed)

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
        self._sort_combo.addItem("По умолчанию", ResultSort.DEFAULT.value)
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
        controls.addLayout(sort_col)
        controls.addLayout(min_col)
        controls.addStretch(1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SP_12)
        root.addLayout(mode_row)
        root.addLayout(filter_row)
        root.addLayout(controls)
        root.addWidget(self._empty_host, stretch=1)
        root.addWidget(self._scroll, stretch=1)
        self._scroll.hide()
        self._sync_mode_buttons()

    def set_results(self, posts: list[AnalyzedPost]) -> None:
        self._posts = self._unique_by_text(posts)
        self._human_labels = {}
        self._received_results = True
        self._near_bottom_emitted = False
        self._render()

    def append_results(self, posts: list[AnalyzedPost]) -> None:
        """Append a new page without rebuilding existing cards (keeps UI responsive)."""
        if not posts:
            self._near_bottom_emitted = False
            return

        before_count = len(self._posts)
        self._posts = self._unique_by_text([*self._posts, *posts])
        self._received_results = True
        self._near_bottom_emitted = False
        added = self._posts[before_count:]
        if not added:
            return

        # First page / empty / non-default sort → full render (order may change).
        if (
            not self._scroll.isVisible()
            or self._sort != ResultSort.DEFAULT
            or before_count == 0
        ):
            bar = self._scroll.verticalScrollBar()
            old_value = bar.value()
            self._render()
            bar.setValue(old_value)
            return

        visible_added = [item for item in added if self._passes_current_filters(item)]
        if visible_added:
            self._empty_host.hide()
            self._scroll.show()
            self._header_run_button.show()
            self._append_cards(visible_added)
        self._check_near_bottom()

    def set_load_more_enabled(self, enabled: bool) -> None:
        self._load_more_enabled = bool(enabled)
        if not self._load_more_enabled:
            self._near_bottom_emitted = False
            return
        # Content may already sit at the bottom (short filtered page).
        QTimer.singleShot(0, self._check_near_bottom)

    def set_loading_more(self, loading: bool, *, hint: str | None = None) -> None:
        """Show/hide circular spinner at the end of the list."""
        self._loading_more = bool(loading)
        if hint:
            self._loading_label.setText(hint)
        elif self._min_views > 0:
            self._loading_label.setText(
                f"Ищем посты с ≥{self._min_views} просмотрами…"
            )
        else:
            self._loading_label.setText("Загрузка постов…")
        if self._loading_more:
            self._ensure_loading_footer()
            self._empty_host.hide()
            self._scroll.show()
            self._header_run_button.show()
            self._loading_footer.show()
            self._spinner.set_spinning(True)
            # Keep the spinner in view while the next page loads.
            bar = self._scroll.verticalScrollBar()
            bar.setValue(bar.maximum())
        else:
            self._spinner.set_spinning(False)
            self._loading_footer.hide()
            self._near_bottom_emitted = False
            self._loading_label.setText("Загрузка постов…")
            # Short lists stay "at bottom" — re-check after the latch clears.
            if self._load_more_enabled:
                QTimer.singleShot(0, self._check_near_bottom)

    def reset_near_bottom_gate(self) -> None:
        self._near_bottom_emitted = False

    def set_feed_exhausted(self, exhausted: bool) -> None:
        self._feed_exhausted = bool(exhausted)

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

    def current_filter(self) -> ResultFilter:
        return self._filter

    def current_scoring_mode(self) -> ScoringMode:
        return self._scoring_mode

    def current_sort(self) -> ResultSort:
        return self._sort

    def current_min_views(self) -> int:
        return self._min_views

    @property
    def posts(self) -> list[AnalyzedPost]:
        """Deduped posts currently held by the view (before filter/sort)."""
        return list(self._posts)

    def visible_posts(self) -> list[AnalyzedPost]:
        posts = [p for p in self._posts if self._passes_current_filters(p)]

        if self._sort == ResultSort.VIEWS_DESC:
            posts.sort(key=lambda p: int(p.post.views or 0), reverse=True)
        elif self._sort == ResultSort.VIEWS_ASC:
            posts.sort(key=lambda p: int(p.post.views or 0))
        elif self._sort == ResultSort.SCORE_DESC:
            posts.sort(key=lambda p: float(self.scoring_for(p).final_score), reverse=True)
        elif self._sort == ResultSort.SCORE_ASC:
            posts.sort(key=lambda p: float(self.scoring_for(p).final_score))
        return posts

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
    def _unique_by_text(posts: list[AnalyzedPost]) -> list[AnalyzedPost]:
        """Keep first post for each normalized text body."""
        unique: list[AnalyzedPost] = []
        seen_texts: set[str] = set()
        for item in posts:
            key = post_text_key(item.post.text)
            if key:
                if key in seen_texts:
                    continue
                seen_texts.add(key)
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
        self.filter_changed.emit(self._filter)
        self._render()

    def _on_sort_changed(self, _index: int) -> None:
        raw = self._sort_combo.currentData()
        try:
            self._sort = ResultSort(str(raw))
        except ValueError:
            self._sort = ResultSort.DEFAULT
        self._render()

    def _on_min_views_changed(self, value: int) -> None:
        self._min_views = max(0, int(value))
        self._render()
        self.min_views_changed.emit(self._min_views)

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

    def _append_cards(self, items: list[AnalyzedPost]) -> None:
        """Insert new cards before the loading footer / trailing stretch."""
        self._ensure_loading_footer()
        insert_at = self._cards_layout.indexOf(self._loading_footer)
        if insert_at < 0:
            insert_at = self._cards_layout.count()
            for index in range(self._cards_layout.count()):
                item = self._cards_layout.itemAt(index)
                if item is not None and item.spacerItem() is not None:
                    insert_at = index
                    break

        for item in items:
            card = self._make_post_card(item)
            self._cards_layout.insertWidget(insert_at, card)
            insert_at += 1

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

    def _render(self) -> None:
        keep_loading = self._loading_more
        self._clear_cards()
        visible = self.visible_posts()

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

        if not visible:
            # Keep fetching until min-views is satisfied (or the feed is exhausted).
            if self._posts and self._min_views > 0 and not self._feed_exhausted:
                self._empty_host.hide()
                self._scroll.show()
                self._header_run_button.show()
                self._cards_layout.addStretch(1)
                self._ensure_loading_footer()
                self._loading_footer.show()
                self._spinner.set_spinning(True)
                self._loading_label.setText(
                    f"Ищем посты с ≥{self._min_views} просмотрами…"
                )
                # MainWindow owns autofill on min-views change — don't emit load-more
                # from here (it races with exhausted/pending flags).
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
        for item in visible:
            self._cards_layout.addWidget(self._make_post_card(item))

        self._cards_layout.addStretch(1)
        self._ensure_loading_footer()
        if keep_loading:
            self._loading_footer.show()
            self._spinner.set_spinning(True)
        else:
            self._loading_footer.hide()
            self._spinner.set_spinning(False)

        self._check_near_bottom()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self._scroll.viewport() and event.type() in {
            QEvent.Type.Wheel,
            QEvent.Type.Scroll,
        }:
            QTimer.singleShot(0, self._check_near_bottom)
        return super().eventFilter(obj, event)

    def _on_scroll_changed(self, _value: int = 0) -> None:
        if not self._is_near_bottom():
            # Allow another request once the user leaves the bottom zone.
            self._near_bottom_emitted = False
        self._check_near_bottom()

    def _on_scroll_range_changed(self, *_args) -> None:
        # New content / filter changes often keep the viewport at the bottom.
        self._near_bottom_emitted = False
        self._check_near_bottom()

    def _is_near_bottom(self) -> bool:
        bar = self._scroll.verticalScrollBar()
        maximum = bar.maximum()
        if maximum <= 0:
            return True
        return (maximum - bar.value()) <= _NEAR_BOTTOM_PX

    def _check_near_bottom(self) -> None:
        if not self._load_more_enabled or self._loading_more:
            return
        if not self._posts:
            return
        if not self._is_near_bottom():
            self._near_bottom_emitted = False
            return
        if self._near_bottom_emitted:
            return
        # Latch before emit so sticky short lists don't flood requests.
        self._near_bottom_emitted = True
        self._load_more_enabled = False
        self.load_more_requested.emit()
