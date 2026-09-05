from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget


class CircleSpinner(QWidget):
    """Lightweight indeterminate circular spinner."""

    def __init__(self, parent: QWidget | None = None, *, size: int = 28) -> None:
        super().__init__(parent)
        self._angle = 0
        self._size = max(16, int(size))
        self.setFixedSize(self._size, self._size)
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)

    def set_spinning(self, spinning: bool) -> None:
        if spinning:
            if not self._timer.isActive():
                self._timer.start()
            self.show()
        else:
            self._timer.stop()
            self.hide()

    def _tick(self) -> None:
        self._angle = (self._angle + 8) % 360
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        inset = 2.5
        rect = QRectF(inset, inset, self._size - 2 * inset, self._size - 2 * inset)

        track = QPen(QColor(152, 152, 157, 60))
        track.setWidthF(2.5)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track)
        painter.drawEllipse(rect)

        arc = QPen(QColor(10, 132, 255))
        arc.setWidthF(2.5)
        arc.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(arc)
        # Qt angles: 1/16th degree, 0 = 3 o'clock, counter-clockwise.
        painter.drawArc(rect, int(-self._angle * 16), int(-90 * 16))
