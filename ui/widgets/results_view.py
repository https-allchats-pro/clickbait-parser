from __future__ import annotations

from enum import Enum

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

        self._empty_label = QLabel("Запустите анализ, чтобы увидеть результаты")
        self._empty_label.setWordWrap(True)

        self._cards_host = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_host)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._cards_host)

        filter_row = QHBoxLayout()
        self._filter_group = QButtonGroup(self)
        self._btn_all = QPushButton("All")
        self._btn_clickbait = QPushButton("Clickbait")
        self._btn_normal = QPushButton("Normal")
        for index, button in enumerate(
            (self._btn_all, self._btn_clickbait, self._btn_normal)
        ):
            button.setCheckable(True)
            self._filter_group.addButton(button, index)
            filter_row.addWidget(button)
        self._btn_all.setChecked(True)
        self._filter_group.idClicked.connect(self._on_filter_clicked)
        filter_row.addStretch(1)

        root = QVBoxLayout(self)
        root.addLayout(filter_row)
        root.addWidget(self._empty_label)
        root.addWidget(scroll, stretch=1)

    def set_results(self, posts: list[AnalyzedPost]) -> None:
        self._posts = list(posts)
        self._received_results = True
        self._render()

    def clear(self) -> None:
        self._posts = []
        self._received_results = False
        self._empty_label.setText("Запустите анализ, чтобы увидеть результаты")
        self._empty_label.show()
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

    def _render(self) -> None:
        self._clear_cards()
        visible = self.visible_posts()

        if not self._received_results:
            self._empty_label.setText("Запустите анализ, чтобы увидеть результаты")
            self._empty_label.show()
            self._cards_layout.addStretch(1)
            return

        if not self._posts:
            self._empty_label.setText("Посты не найдены")
            self._empty_label.show()
            self._cards_layout.addStretch(1)
            return

        if not visible:
            self._empty_label.setText("Нет постов для выбранного фильтра")
            self._empty_label.show()
            self._cards_layout.addStretch(1)
            return

        self._empty_label.hide()
        for item in visible:
            card = PostCard()
            card.set_post(item)
            self._cards_layout.addWidget(card)
        self._cards_layout.addStretch(1)
