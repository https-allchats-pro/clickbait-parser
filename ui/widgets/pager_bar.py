from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QWidget,
)

from ui.theme import SP_4, SP_8, SP_12


class PagerBar(QWidget):
    """Classic pager: ← prev | page numbers | next → + page size."""

    prev_requested = pyqtSignal()
    next_requested = pyqtSignal()
    page_requested = pyqtSignal(int)  # 1-based page number
    page_size_changed = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None, *, default_size: int = 20) -> None:
        super().__init__(parent)
        self._current = 1
        self._total = 0
        self._has_more = False
        self._busy = False
        self._page_buttons: list[QPushButton] = []

        self._prev = QPushButton("← Назад")
        self._prev.setObjectName("filterButton")
        self._prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self._prev.clicked.connect(self.prev_requested.emit)

        self._next = QPushButton("Вперёд →")
        self._next.setObjectName("filterButton")
        self._next.setCursor(Qt.CursorShape.PointingHandCursor)
        self._next.clicked.connect(self.next_requested.emit)

        self._pages_host = QFrame()
        self._pages_row = QHBoxLayout(self._pages_host)
        self._pages_row.setContentsMargins(0, 0, 0, 0)
        self._pages_row.setSpacing(SP_4)

        size_label = QLabel("На странице")
        size_label.setObjectName("sectionLabel")
        self._size_input = QSpinBox()
        self._size_input.setMinimum(5)
        self._size_input.setMaximum(100)
        self._size_input.setSingleStep(5)
        self._size_input.setValue(default_size)
        self._size_input.setFixedWidth(72)
        self._size_input.setToolTip("Сколько постов загружать и показывать на одной странице")
        self._size_input.valueChanged.connect(self.page_size_changed.emit)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, SP_8, 0, 0)
        root.setSpacing(SP_8)
        root.addWidget(self._prev)
        root.addWidget(self._pages_host)
        root.addWidget(self._next)
        root.addStretch(1)
        root.addWidget(size_label)
        root.addWidget(self._size_input)

        self.set_pagination(current=1, total=0, has_more=False, busy=False)

    def page_size(self) -> int:
        return int(self._size_input.value())

    def set_page_size(self, value: int, *, emit: bool = False) -> None:
        value = max(5, min(100, int(value)))
        self._size_input.blockSignals(True)
        self._size_input.setValue(value)
        self._size_input.blockSignals(False)
        if emit:
            self.page_size_changed.emit(value)

    def set_pagination(
        self,
        *,
        current: int,
        total: int,
        has_more: bool,
        busy: bool = False,
    ) -> None:
        self._current = max(1, int(current))
        self._total = max(0, int(total))
        self._has_more = bool(has_more)
        self._busy = bool(busy)
        self._rebuild_page_buttons()
        self._prev.setEnabled(not busy and self._current > 1)
        # Next stays available whenever there is a list — user can always ask
        # for the next local page or another VK fetch.
        self._next.setEnabled(not busy and self._total > 0)
        self._size_input.setEnabled(not busy)
        self.setVisible(self._total > 0 or busy)

    def _rebuild_page_buttons(self) -> None:
        while self._pages_row.count():
            taken = self._pages_row.takeAt(0)
            widget = taken.widget() if taken is not None else None
            if widget is not None:
                widget.deleteLater()
        self._page_buttons.clear()
        if self._total <= 0:
            return

        for page in self._pages_to_render():
            if page is None:
                dots = QLabel("…")
                dots.setObjectName("sectionLabel")
                self._pages_row.addWidget(dots)
                continue
            btn = QPushButton(str(page))
            btn.setObjectName("filterButton")
            btn.setCheckable(True)
            btn.setChecked(page == self._current)
            btn.setEnabled(not self._busy)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedWidth(36)
            btn.clicked.connect(lambda _checked=False, p=page: self.page_requested.emit(p))
            self._pages_row.addWidget(btn)
            self._page_buttons.append(btn)

    def _pages_to_render(self) -> list[int | None]:
        """Page numbers to show; ``None`` is an ellipsis gap.

        Always includes 1 and the last page so a small sliding window never
        hides page 5+ behind a fake \"max of 4\" look.
        """
        total = self._total
        current = min(max(1, self._current), total)
        if total <= 7:
            return list(range(1, total + 1))

        # Keep a compact neighborhood around the current page.
        radius = 2
        mid_start = max(2, current - radius)
        mid_end = min(total - 1, current + radius)
        # Ensure the middle block has some width even at the edges.
        if mid_end - mid_start < 4:
            if mid_start == 2:
                mid_end = min(total - 1, mid_start + 4)
            if mid_end == total - 1:
                mid_start = max(2, mid_end - 4)

        pages: list[int | None] = [1]
        if mid_start > 2:
            pages.append(None)
        pages.extend(range(mid_start, mid_end + 1))
        if mid_end < total - 1:
            pages.append(None)
        pages.append(total)
        return pages
