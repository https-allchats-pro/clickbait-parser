from __future__ import annotations

from PyQt6.QtCore import QUrl, Qt, pyqtSignal
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

from domain.dataset import DatasetLabel
from domain.pipeline import AnalyzedPost
from domain.scoring import (
    DEFAULT_SCORING_CONFIG,
    PostScoring,
    ScoringConfig,
    ScoringMode,
    compute_post_scoring,
)
from ui.formatters import (
    format_links_label,
    format_post_date,
    format_reason,
    format_score_or_dash,
    format_score_percent,
    format_views_label,
)
from ui.theme import SP_4, SP_8, SP_12, SP_16
from ui.widgets.flow_layout import FlowLayout


class PostCard(QFrame):
    """Polished analyzed-post card (presentation only)."""

    label_requested = pyqtSignal(int, object)  # local post id, DatasetLabel

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("postCard")
        self.setFrameShape(QFrame.Shape.NoFrame)

        self._post_text = ""
        self._link_urls: list[str] = []
        self._post_url: str | None = None
        self._local_post_id: int | None = None
        self._human_label: DatasetLabel | None = None
        self._analyzed: AnalyzedPost | None = None
        self._scoring: PostScoring | None = None
        self._breakdown_open = False

        self._prediction = QLabel()
        self._score = QLabel()
        self._score.setObjectName("scoreBadge")
        self._score.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

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

        self._open_post_button = QPushButton("Открыть пост")
        self._open_post_button.setObjectName("linkButton")
        self._open_post_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_post_button.setToolTip("Открыть пост во VK")
        self._open_post_button.clicked.connect(self._on_open_post)

        self._btn_clickbait = QPushButton("👍 Кликбейт")
        self._btn_clickbait.setObjectName("labelGood")
        self._btn_clickbait.setCheckable(True)
        self._btn_clickbait.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_clickbait.setToolTip("Пометить как кликбейт для обучения ML")
        self._btn_clickbait.clicked.connect(
            lambda: self._on_label_clicked(DatasetLabel.CLICKBAIT)
        )

        self._btn_normal = QPushButton("👎 Обычный")
        self._btn_normal.setObjectName("labelBad")
        self._btn_normal.setCheckable(True)
        self._btn_normal.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_normal.setToolTip("Пометить как обычный пост для обучения ML")
        self._btn_normal.clicked.connect(
            lambda: self._on_label_clicked(DatasetLabel.NORMAL)
        )

        self._btn_borderline = QPushButton("± Спорно")
        self._btn_borderline.setObjectName("labelBorderline")
        self._btn_borderline.setCheckable(True)
        self._btn_borderline.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_borderline.setToolTip("Сомнительный пример (borderline)")
        self._btn_borderline.clicked.connect(
            lambda: self._on_label_clicked(DatasetLabel.BORDERLINE)
        )

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(SP_8)
        header.addWidget(self._prediction, alignment=Qt.AlignmentFlag.AlignLeft)
        header.addWidget(self._copy_button, alignment=Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self._open_post_button, alignment=Qt.AlignmentFlag.AlignVCenter)
        header.addStretch(1)
        header.addWidget(self._score)

        self._rules_row = self._score_row("Rules")
        self._ml_row = self._score_row("ML")
        self._final_row = self._score_row("Final")

        scores_block = QVBoxLayout()
        scores_block.setContentsMargins(0, 0, 0, 0)
        scores_block.setSpacing(SP_4)
        scores_block.addLayout(self._rules_row)
        scores_block.addLayout(self._ml_row)
        scores_block.addLayout(self._final_row)

        self._details_button = QPushButton("Score breakdown")
        self._details_button.setObjectName("filterButton")
        self._details_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._details_button.setCheckable(True)
        self._details_button.clicked.connect(self._toggle_breakdown)

        self._breakdown = QLabel()
        self._breakdown.setObjectName("metaLabel")
        self._breakdown.setWordWrap(True)
        self._breakdown.hide()

        label_row = QHBoxLayout()
        label_row.setContentsMargins(0, 0, 0, 0)
        label_row.setSpacing(SP_8)
        label_row.addWidget(self._btn_clickbait)
        label_row.addWidget(self._btn_normal)
        label_row.addWidget(self._btn_borderline)
        label_row.addStretch(1)

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
        divider.setObjectName("cardDivider")
        divider.setFrameShape(QFrame.Shape.HLine)

        self._reasons_title = QLabel("Причины")
        self._reasons_title.setObjectName("reasonsTitle")

        self._chips_host = QWidget()
        self._chips_layout = FlowLayout(self._chips_host, spacing=SP_8)
        self._chips_host.setLayout(self._chips_layout)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SP_16, SP_16, SP_16, SP_16)
        layout.setSpacing(SP_12)
        layout.addLayout(header)
        layout.addLayout(scores_block)
        layout.addWidget(self._details_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._breakdown)
        layout.addLayout(label_row)
        layout.addWidget(self._text_label)
        layout.addWidget(divider)
        layout.addLayout(meta_row)
        layout.addWidget(self._reasons_title)
        layout.addWidget(self._chips_host)

    @staticmethod
    def _score_row(caption: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(SP_8)
        name = QLabel(caption)
        name.setObjectName("metaLabel")
        name.setFixedWidth(48)
        value = QLabel("—")
        value.setObjectName("metaLabel")
        row.addWidget(name)
        row.addWidget(value)
        row.addStretch(1)
        row._value_label = value  # type: ignore[attr-defined]
        return row

    def set_post(
        self,
        analyzed_post: AnalyzedPost,
        *,
        mode: ScoringMode = ScoringMode.RULES,
        config: ScoringConfig = DEFAULT_SCORING_CONFIG,
    ) -> None:
        post = analyzed_post.post
        analysis = analyzed_post.analysis
        self._analyzed = analyzed_post
        self._local_post_id = post.id
        self._human_label = None
        self._breakdown_open = False
        self._details_button.setChecked(False)
        self._breakdown.hide()

        scoring = compute_post_scoring(
            rules_score=analyzed_post.rules_score,
            ml_score=analyzed_post.ml_score,
            mode=mode,
            config=config,
        )
        self._scoring = scoring
        self._apply_scoring(scoring)

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

        self._post_url = post.wall_url()
        if self._post_url:
            self._open_post_button.setEnabled(True)
            self._open_post_button.setToolTip(self._post_url)
            self._open_post_button.show()
        else:
            self._open_post_button.setEnabled(False)
            self._open_post_button.setToolTip("")
            self._open_post_button.hide()

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

        can_label = self._local_post_id is not None
        for button in (self._btn_clickbait, self._btn_normal, self._btn_borderline):
            button.setEnabled(can_label)
        self._apply_human_label(None)
        self._copy_button.setToolTip("Copy post text")

    def _apply_scoring(self, scoring: PostScoring) -> None:
        is_clickbait = bool(scoring.is_clickbait)
        badge = "🔴 Clickbait" if is_clickbait else "🟢 Not clickbait"
        self._prediction.setText(badge)
        self._prediction.setObjectName(
            "predictionClickbait" if is_clickbait else "predictionNormal"
        )
        self._prediction.style().unpolish(self._prediction)
        self._prediction.style().polish(self._prediction)

        self._score.setText(format_score_percent(scoring.final_score))
        self._rules_row._value_label.setText(  # type: ignore[attr-defined]
            format_score_percent(scoring.rules_score)
        )
        self._ml_row._value_label.setText(  # type: ignore[attr-defined]
            format_score_or_dash(scoring.ml_score)
        )
        self._final_row._value_label.setText(  # type: ignore[attr-defined]
            f"{format_score_percent(scoring.final_score)}   {badge}"
        )

    def _toggle_breakdown(self, checked: bool) -> None:
        self._breakdown_open = bool(checked)
        if not self._breakdown_open or self._scoring is None or self._analyzed is None:
            self._breakdown.hide()
            return
        self._breakdown.setText(self._build_breakdown_text(self._scoring, self._analyzed))
        self._breakdown.show()

    @staticmethod
    def _build_breakdown_text(scoring: PostScoring, analyzed: AnalyzedPost) -> str:
        lines = [
            f"Clickbait score: {format_score_percent(scoring.final_score)}",
            "",
            "Rules contribution",
        ]
        hits = analyzed.analysis.rule_contributions
        if hits:
            for hit in hits:
                lines.append(
                    f"  {format_reason(hit.reason):<28} +{hit.weight:.2f}"
                )
        else:
            lines.append("  (no rules matched)")

        lines.append("")
        lines.append("ML contribution")
        if scoring.ml_score is None:
            lines.append("  Model not trained")
        else:
            lines.append(
                f"  ML probability             {format_score_percent(scoring.ml_score)}"
            )

        lines.append("")
        lines.append("Final")
        if scoring.mode == ScoringMode.RULES or not scoring.used_ml:
            lines.append("  Mode                      Rules only")
        elif scoring.mode == ScoringMode.ML:
            lines.append("  Mode                      ML only")
        else:
            lines.append(
                f"  Rules weight              {round(scoring.rules_weight * 100)}%"
            )
            lines.append(
                f"  ML weight                 {round(scoring.ml_weight * 100)}%"
            )
        lines.append(
            f"  Threshold                 {format_score_percent(scoring.threshold)}"
        )
        lines.append(
            f"  Final score               {format_score_percent(scoring.final_score)}"
        )
        return "\n".join(lines)

    def set_human_label(self, label: DatasetLabel | None) -> None:
        self._apply_human_label(label)

    def _apply_human_label(self, label: DatasetLabel | None) -> None:
        self._human_label = label
        self._btn_clickbait.setChecked(label == DatasetLabel.CLICKBAIT)
        self._btn_normal.setChecked(label == DatasetLabel.NORMAL)
        self._btn_borderline.setChecked(label == DatasetLabel.BORDERLINE)

    def _on_label_clicked(self, label: DatasetLabel) -> None:
        if self._local_post_id is None:
            self._apply_human_label(self._human_label)
            return
        # Optimistic UI; MainWindow persists and may refresh.
        self._apply_human_label(label)
        self.label_requested.emit(int(self._local_post_id), label)

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

    def _on_open_post(self) -> None:
        if not self._post_url:
            return
        QDesktopServices.openUrl(QUrl(self._post_url))

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
