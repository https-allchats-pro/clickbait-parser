from __future__ import annotations

from enum import Enum

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from domain.pipeline import AnalyzedPost
from ui.theme import SP_8, SP_12
from ui.widgets.post_card import PostCard


class ResultFilter(str, Enum):
    ALL = "all"
    CLICKBAIT = "clickbait"
    NORMAL = "normal"


class ResultsView(QWidget):
    """Scrollable list of AnalyzedPost cards with client-side filter."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._posts: list[AnalyzedPost] = []
        self._filter = ResultFilter.ALL
        self._received_results = False

        self._empty_title = QLabel("Запустите анализ")
        self._empty_title.setObjectName("emptyTitle")
        self._empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint = QLabel("Результаты появятся здесь после запуска.")
        self._empty_hint.setObjectName("emptyHint")
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint.setWordWrap(True)

        empty_box = QVBoxLayout()
        empty_box.setSpacing(SP_8)
        empty_box.addStretch(1)
        empty_box.addWidget(self._empty_title)
        empty_box.addWidget(self._empty_hint)
        empty_box.addStretch(2)
        self._empty_host = QWidget()
        self._empty_host.setLayout(empty_box)

        self._cards_host = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_host)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(SP_12)
        self._cards_layout.addStretch(1)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(self._cards_host)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(SP_8)
        self._filter_group = QButtonGroup(self)
        self._btn_all = QPushButton("All")
        self._btn_clickbait = QPushButton("Clickbait")
        self._btn_normal = QPushButton("Normal")
        for index, button in enumerate(
            (self._btn_all, self._btn_clickbait, self._btn_normal)
        ):
            button.setObjectName("filterButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._filter_group.addButton(button, index)
            filter_row.addWidget(button)
        self._btn_all.setChecked(True)
        self._filter_group.idClicked.connect(self._on_filter_clicked)
        filter_row.addStretch(1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SP_12)
        root.addLayout(filter_row)
        root.addWidget(self._empty_host, stretch=1)
        root.addWidget(self._scroll, stretch=1)
        self._scroll.hide()

    def set_results(self, posts: list[AnalyzedPost]) -> None:
        self._posts = list(posts)
        self._received_results = True
        self._render()

    def clear(self) -> None:
        self._posts = []
        self._received_results = False
        self._render()

    def set_filter(self, value: ResultFilter) -> None:
        self._filter = value
        mapping = {
            ResultFilter.ALL: self._btn_all,
            ResultFilter.CLICKBAIT: self._btn_clickbait,
            ResultFilter.NORMAL: self._btn_normal,
        }
        mapping[value].setChecked(True)
        self._render()

    def current_filter(self) -> ResultFilter:
        return self._filter

    def visible_posts(self) -> list[AnalyzedPost]:
        if self._filter == ResultFilter.CLICKBAIT:
            return [p for p in self._posts if p.analysis.is_clickbait]
        if self._filter == ResultFilter.NORMAL:
            return [p for p in self._posts if not p.analysis.is_clickbait]
        return list(self._posts)

    def _on_filter_clicked(self, button_id: int) -> None:
        mapping = {
            0: ResultFilter.ALL,
            1: ResultFilter.CLICKBAIT,
            2: ResultFilter.NORMAL,
        }
        self._filter = mapping.get(button_id, ResultFilter.ALL)
        self._render()

    def _clear_cards(self) -> None:
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _show_empty(self, title: str, hint: str) -> None:
        self._empty_title.setText(title)
        self._empty_hint.setText(hint)
        self._empty_host.show()
        self._scroll.hide()

    def _render(self) -> None:
        self._clear_cards()
        visible = self.visible_posts()

        if not self._received_results:
            self._show_empty(
                "Запустите анализ",
                "Результаты появятся здесь после запуска.",
            )
            self._cards_layout.addStretch(1)
            return

        if not self._posts:
            self._show_empty(
                "Посты не найдены",
                "Попробуйте изменить запрос или увеличить лимит.",
            )
            self._cards_layout.addStretch(1)
            return

        if not visible:
            self._show_empty(
                "Нет постов для выбранного фильтра",
                "Переключите фильтр All / Clickbait / Normal.",
            )
            self._cards_layout.addStretch(1)
            return

        self._empty_host.hide()
        self._scroll.show()
        for item in visible:
            card = PostCard()
            card.set_post(item)
            self._cards_layout.addWidget(card)
        self._cards_layout.addStretch(1)
