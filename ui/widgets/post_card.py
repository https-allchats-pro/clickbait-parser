from __future__ import annotations

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QDesktopServices, QGuiApplication, QIcon
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from domain.pipeline import AnalyzedPost
from ui.formatters import (
    format_links_label,
    format_post_date,
    format_reason,
    format_score_percent,
    format_views_label,
)
from ui.theme import SP_8, SP_12, SP_16
from ui.widgets.flow_layout import FlowLayout


class PostCard(QFrame):
    """Polished analyzed-post card (presentation only)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("postCard")
        self.setFrameShape(QFrame.Shape.NoFrame)

        self._post_text = ""
        self._link_urls: list[str] = []

        self._prediction = QLabel()
        self._score = QLabel()
        self._score.setObjectName("scoreBadge")
        self._score.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(SP_8)
        header.addWidget(self._prediction, alignment=Qt.AlignmentFlag.AlignLeft)
        header.addStretch(1)
        header.addWidget(self._score)

        self._text_label = QLabel()
        self._text_label.setObjectName("postText")
        self._text_label.setWordWrap(True)
        self._text_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self._meta_label = QLabel()
        self._meta_label.setObjectName("metaLabel")
        self._meta_label.setWordWrap(True)

        self._links_button = QPushButton()
        self._links_button.setObjectName("linkButton")
        self._links_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._links_button.clicked.connect(self._on_links_clicked)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(SP_12)
        meta_row.addWidget(self._meta_label, stretch=1)
        meta_row.addWidget(self._links_button, alignment=Qt.AlignmentFlag.AlignRight)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("color: #3a3a3c; background: #3a3a3c; max-height: 1px;")

        self._reasons_title = QLabel("Причины")
        self._reasons_title.setObjectName("reasonsTitle")

        self._chips_host = QWidget()
        self._chips_layout = FlowLayout(self._chips_host, spacing=SP_8)
        self._chips_host.setLayout(self._chips_layout)

        self._copy_button = QToolButton()
        self._copy_button.setObjectName("iconButton")
        self._copy_button.setToolTip("Copy post text")
        self._copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        icon = QIcon.fromTheme("edit-copy")
        if icon.isNull():
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        self._copy_button.setIcon(icon)
        self._copy_button.setText("Copy")
        self._copy_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._copy_button.clicked.connect(self._on_copy)

        footer = QHBoxLayout()
        footer.addStretch(1)
        footer.addWidget(self._copy_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SP_16, SP_16, SP_16, SP_16)
        layout.setSpacing(SP_12)
        layout.addLayout(header)
        layout.addWidget(self._text_label)
        layout.addWidget(divider)
        layout.addLayout(meta_row)
        layout.addWidget(self._reasons_title)
        layout.addWidget(self._chips_host)
        layout.addLayout(footer)

    def set_post(self, analyzed_post: AnalyzedPost) -> None:
        post = analyzed_post.post
        analysis = analyzed_post.analysis

        is_clickbait = bool(analysis.is_clickbait)
        self._prediction.setText("CLICKBAIT" if is_clickbait else "NORMAL")
        self._prediction.setObjectName(
            "predictionClickbait" if is_clickbait else "predictionNormal"
        )
        self._prediction.style().unpolish(self._prediction)
        self._prediction.style().polish(self._prediction)

        self._score.setText(format_score_percent(analysis.score))

        text = (post.text or "").strip() or "(empty)"
        self._post_text = text
        self._text_label.setText(text)

        when = format_post_date(post.date)
        source = "VK Catalog" if post.source.startswith("vk") else post.source
        views = format_views_label(post.views)
        self._meta_label.setText(f"{source}  ·  {when}  ·  {views}")
        self._meta_label.setToolTip(
            f"Owner ID: {post.owner_id}\nPost ID: {post.post_id}\nViews: {post.views}"
        )

        self._link_urls = [link.url for link in post.links if link.url]
        count = len(self._link_urls)
        self._links_button.setText(format_links_label(count))
        self._links_button.setEnabled(count > 0)
        if count == 1:
            self._links_button.setToolTip(self._link_urls[0])
        elif count > 1:
            self._links_button.setToolTip("Открыть ссылки")
        else:
            self._links_button.setToolTip("")

        self._clear_chips()
        if analysis.reasons:
            self._reasons_title.show()
            self._chips_host.show()
            for reason in analysis.reasons:
                chip = QLabel(format_reason(reason))
                chip.setObjectName("reasonChip")
                self._chips_layout.addWidget(chip)
        else:
            self._reasons_title.hide()
            self._chips_host.hide()

        self._copy_button.setToolTip("Copy post text")

    def _clear_chips(self) -> None:
        while self._chips_layout.count():
            item = self._chips_layout.takeAt(0)
            if item is None:
                break
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _on_copy(self) -> None:
        QGuiApplication.clipboard().setText(self._post_text)
        self._copy_button.setToolTip("Copied")

    def _on_links_clicked(self) -> None:
        if not self._link_urls:
            return
        if len(self._link_urls) == 1:
            QDesktopServices.openUrl(QUrl(self._link_urls[0]))
            return
        menu = QMenu(self)
        for url in self._link_urls:
            action = menu.addAction(url)
            action.triggered.connect(lambda _checked=False, u=url: QDesktopServices.openUrl(QUrl(u)))
        menu.exec(self._links_button.mapToGlobal(self._links_button.rect().bottomLeft()))
