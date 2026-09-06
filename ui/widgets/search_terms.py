from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.theme import SP_4, SP_8
from ui.widgets.flow_layout import FlowLayout


class SearchTermsBar(QWidget):
    """Line edit + removable chips. Enter adds the current word as a search term."""

    terms_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._terms: list[str] = []

        label = QLabel("Search")
        label.setObjectName("sectionLabel")

        self._input = QLineEdit()
        self._input.setPlaceholderText("слово + Enter · несколько слов подряд")
        self._input.returnPressed.connect(self._on_return_pressed)

        self._chips_host = QFrame()
        self._chips_host.setObjectName("searchChipsHost")
        self._chips_layout = FlowLayout(self._chips_host, spacing=SP_8)
        self._chips_host.setLayout(self._chips_layout)
        self._chips_host.hide()

        hint = QLabel("Enter — добавить слово. Анализ ищет по 20 постов на каждое.")
        hint.setObjectName("statusFooter")
        hint.setWordWrap(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SP_4)
        root.addWidget(label)
        root.addWidget(self._input)
        root.addWidget(self._chips_host)
        root.addWidget(hint)

    @property
    def input(self) -> QLineEdit:
        return self._input

    def terms(self) -> list[str]:
        return list(self._terms)

    def set_terms(self, terms: list[str]) -> None:
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in terms:
            term = str(raw).strip()
            if not term:
                continue
            key = term.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(term)
        self._terms = cleaned
        self._rebuild_chips()
        self.terms_changed.emit()

    def clear_terms(self) -> None:
        self.set_terms([])

    def commit_input(self) -> bool:
        """Add current input text as a term (Analyse / explicit commit)."""
        return self._add_term(self._input.text())

    def _on_return_pressed(self) -> None:
        self._add_term(self._input.text())

    def _add_term(self, raw: str) -> bool:
        term = raw.strip()
        if not term:
            return False
        key = term.casefold()
        if any(t.casefold() == key for t in self._terms):
            self._input.clear()
            return False
        self._terms.append(term)
        self._input.clear()
        self._rebuild_chips()
        self.terms_changed.emit()
        return True

    def _remove_term(self, term: str) -> None:
        key = term.casefold()
        self._terms = [t for t in self._terms if t.casefold() != key]
        self._rebuild_chips()
        self.terms_changed.emit()

    def _rebuild_chips(self) -> None:
        while self._chips_layout.count():
            taken = self._chips_layout.takeAt(0)
            widget = taken.widget() if taken is not None else None
            if widget is not None:
                widget.deleteLater()
        if not self._terms:
            self._chips_host.hide()
            return
        for term in self._terms:
            chip = QPushButton(f"{term}  ×")
            chip.setObjectName("searchChip")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setToolTip("Убрать из поиска")
            chip.clicked.connect(lambda _checked=False, t=term: self._remove_term(t))
            self._chips_layout.addWidget(chip)
        self._chips_host.show()
