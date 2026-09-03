from __future__ import annotations

from datetime import datetime

from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from domain.pipeline import AnalyzedPost


class PostCard(QFrame):
    """Single analyzed post card (presentation only)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setLineWidth(1)

        self._score_label = QLabel()
        self._meta_label = QLabel()
        self._meta_label.setWordWrap(True)
        self._text_label = QLabel()
        self._text_label.setWordWrap(True)
        self._reasons_label = QLabel()
        self._reasons_label.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(self._score_label)
        layout.addWidget(self._meta_label)
        layout.addWidget(self._text_label)
        layout.addWidget(self._reasons_label)

    def set_post(self, analyzed_post: AnalyzedPost) -> None:
        post = analyzed_post.post
        analysis = analyzed_post.analysis
        prediction = "CLICKBAIT" if analysis.is_clickbait else "NORMAL"
        self._score_label.setText(f"{analysis.score:0.2f}  {prediction}")

        when = (
            post.date.astimezone().strftime("%Y-%m-%d %H:%M")
            if isinstance(post.date, datetime)
            else "?"
        )
        self._meta_label.setText(
            f"owner={post.owner_id}  post={post.post_id}  date={when}  links={len(post.links)}"
        )
        self._text_label.setText(post.text.strip() or "(empty)")

        if analysis.reasons:
            bullets = "\n".join(f"• {reason}" for reason in analysis.reasons)
            self._reasons_label.setText(f"Reasons:\n{bullets}")
        else:
            self._reasons_label.setText("Reasons:\n• (none)")
