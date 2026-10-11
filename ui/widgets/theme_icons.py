from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

# Rendered above 1x so the icon stays crisp on HiDPI / Retina screens.
_SCALE = 3


def _canvas(size: int) -> tuple[QPixmap, QPainter]:
    pixmap = QPixmap(size * _SCALE, size * _SCALE)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(_SCALE)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    return pixmap, painter


def sun_icon(color: str, size: int = 18) -> QIcon:
    pixmap, painter = _canvas(size)
    c = size / 2
    stroke = max(1.5, size / 11)

    pen = QPen(QColor(color))
    pen.setWidthF(stroke)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    core = size * 0.2
    painter.drawEllipse(QPointF(c, c), core, core)

    inner, outer = size * 0.34, size * 0.46
    for i in range(8):
        angle = math.pi / 4 * i
        dx, dy = math.cos(angle), math.sin(angle)
        painter.drawLine(
            QPointF(c + dx * inner, c + dy * inner),
            QPointF(c + dx * outer, c + dy * outer),
        )
    painter.end()
    return QIcon(pixmap)


def moon_icon(color: str, size: int = 18) -> QIcon:
    pixmap, painter = _canvas(size)
    pad = size * 0.12
    body = QRectF(pad, pad, size - 2 * pad, size - 2 * pad)

    disc = QPainterPath()
    disc.addEllipse(body)
    bite = QPainterPath()
    shift = body.width() * 0.38
    bite.addEllipse(body.translated(shift, -shift))
    crescent = disc.subtracted(bite)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawPath(crescent)
    painter.end()
    return QIcon(pixmap)
