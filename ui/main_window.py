from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from domain.pipeline import PipelineProgress, PipelineRequest, PipelineResult, PipelineState
from ui.formatters import human_state
from ui.theme import SP_4, SP_8, SP_12, SP_16, SP_24
from ui.widgets.results_view import ResultsView


class MainWindow(QMainWindow):
    """Presentation shell: inputs, progress, results. No VK/SQLite/pipeline logic."""

    run_requested = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("clickbait-parser")
        self.resize(980, 760)
        self.setMinimumSize(900, 650)

        self._query_input = QLineEdit()
        self._query_input.setPlaceholderText("искать продолжение, новости…")

        self._limit_input = QSpinBox()
        self._limit_input.setMinimum(1)
        self._limit_input.setMaximum(10_000)
        self._limit_input.setValue(100)
        self._limit_input.setFixedWidth(100)

        self._run_button = QPushButton("Анализ")
        self._run_button.setObjectName("primaryButton")
        self._run_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._run_button.clicked.connect(self._on_run_clicked)

        search_label = QLabel("Search")
        search_label.setObjectName("sectionLabel")
        limit_label = QLabel("Limit")
        limit_label.setObjectName("sectionLabel")

        limit_row = QHBoxLayout()
        limit_row.setSpacing(SP_12)
        limit_col = QVBoxLayout()
        limit_col.setSpacing(SP_4)
        limit_col.addWidget(limit_label)
        limit_col.addWidget(self._limit_input)
        limit_row.addLayout(limit_col)
        limit_row.addStretch(1)
        limit_row.addWidget(self._run_button, alignment=Qt.AlignmentFlag.AlignBottom)

        form = QVBoxLayout()
        form.setSpacing(SP_12)
        form.addWidget(search_label)
        form.addWidget(self._query_input)
        form.addLayout(limit_row)

        toolbar = QFrame()
        toolbar.setObjectName("panel")
        toolbar_layout = QVBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(SP_16, SP_16, SP_16, SP_16)
        toolbar_layout.setSpacing(SP_8)
        toolbar_layout.addLayout(form)

        self._progress_title = QLabel(human_state(PipelineState.IDLE))
        self._progress_title.setObjectName("progressTitle")
        self._progress_count = QLabel("—")
        self._progress_count.setObjectName("progressCount")
        self._progress_count.setAlignment(Qt.AlignmentFlag.AlignRight)

        progress_header = QHBoxLayout()
        progress_header.addWidget(self._progress_title)
        progress_header.addStretch(1)
        progress_header.addWidget(self._progress_count)

        self._progress_bar = QProgressBar()
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(8)

        self._status_footer = QLabel(human_state(PipelineState.IDLE))
        self._status_footer.setObjectName("statusFooter")

        progress_panel = QFrame()
        progress_panel.setObjectName("panel")
        progress_layout = QVBoxLayout(progress_panel)
        progress_layout.setContentsMargins(SP_16, SP_12, SP_16, SP_12)
        progress_layout.setSpacing(SP_8)
        progress_layout.addLayout(progress_header)
        progress_layout.addWidget(self._progress_bar)
        progress_layout.addWidget(self._status_footer)

        self._stat_posts = self._make_stat_card("0", "Posts")
        self._stat_clickbait = self._make_stat_card("0", "Clickbait")
        self._stat_normal = self._make_stat_card("0", "Normal")
        stats_row = QHBoxLayout()
        stats_row.setSpacing(SP_12)
        for card in (self._stat_posts, self._stat_clickbait, self._stat_normal):
            stats_row.addWidget(card, stretch=1)
        self._stats_host = QWidget()
        self._stats_host.setLayout(stats_row)

        self._error_title = QLabel("Не удалось выполнить анализ")
        self._error_title.setObjectName("errorTitle")
        self._error_detail = QLabel()
        self._error_detail.setObjectName("errorDetail")
        self._error_detail.setWordWrap(True)
        self._retry_button = QPushButton("Попробовать снова")
        self._retry_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._retry_button.clicked.connect(self._on_run_clicked)

        error_inner = QVBoxLayout()
        error_inner.setSpacing(SP_8)
        error_inner.addWidget(self._error_title)
        error_inner.addWidget(self._error_detail)
        error_inner.addWidget(self._retry_button, alignment=Qt.AlignmentFlag.AlignLeft)

        self._error_panel = QFrame()
        self._error_panel.setObjectName("errorPanel")
        self._error_panel.setLayout(error_inner)
        self._error_panel.hide()

        self._results = ResultsView()

        root = QVBoxLayout()
        root.setContentsMargins(SP_24, SP_24, SP_24, SP_24)
        root.setSpacing(SP_16)
        root.addWidget(toolbar)
        root.addWidget(progress_panel)
        root.addWidget(self._stats_host)
        root.addWidget(self._error_panel)
        root.addWidget(self._results, stretch=1)

        container = QWidget()
        container.setLayout(root)
        self.setCentralWidget(container)

        self._controller: object | None = None

    def _make_stat_card(self, value: str, caption: str) -> QFrame:
        card = QFrame()
        card.setObjectName("statCard")
        value_label = QLabel(value)
        value_label.setObjectName("statValue")
        caption_label = QLabel(caption)
        caption_label.setObjectName("statCaption")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(SP_16, SP_12, SP_16, SP_12)
        layout.setSpacing(SP_4)
        layout.addWidget(value_label)
        layout.addWidget(caption_label)
        card._value_label = value_label  # type: ignore[attr-defined]
        return card

    def set_controller(self, controller: object) -> None:
        """Keep a strong reference so the controller is not garbage-collected."""
        self._controller = controller

    @property
    def results_view(self) -> ResultsView:
        return self._results

    def build_request(self) -> PipelineRequest:
        query = self._query_input.text().strip() or None
        return PipelineRequest(limit=int(self._limit_input.value()), query=query)

    def set_running(self, running: bool) -> None:
        self._run_button.setEnabled(not running)
        self._query_input.setEnabled(not running)
        self._limit_input.setEnabled(not running)
        self._retry_button.setEnabled(not running)
        if running:
            self._run_button.setText("Анализируется...")
            self.clear_error()
        else:
            self._run_button.setText("Анализ")

    def apply_progress(self, progress: PipelineProgress) -> None:
        title = human_state(progress.state)
        self._progress_title.setText(title)
        total = max(0, int(progress.total))
        current = max(0, int(progress.current))
        if total > 0:
            self._progress_bar.setMaximum(total)
            self._progress_bar.setValue(min(current, total))
            pct = int(round(100 * min(current, total) / total))
            self._progress_count.setText(f"{current} / {total}   ·   {pct}%")
        else:
            self._progress_bar.setMaximum(1)
            self._progress_bar.setValue(
                1 if progress.state == PipelineState.COMPLETED else 0
            )
            self._progress_count.setText(f"{current} / {total}")
        self._status_footer.setText(title)

    def show_result(self, result: PipelineResult) -> None:
        self.apply_progress(
            PipelineProgress(
                state=PipelineState.COMPLETED,
                current=max(result.analyzed, len(result.posts)),
                total=max(result.analyzed, len(result.posts), 1),
            )
        )
        if not result.posts:
            self._progress_count.setText("0 / 0")
            self._progress_bar.setMaximum(1)
            self._progress_bar.setValue(0)

        posts = result.posts
        clickbait = sum(1 for item in posts if item.analysis.is_clickbait)
        normal = len(posts) - clickbait
        self._set_stats(len(posts), clickbait, normal)
        self._results.set_results(posts)
        self.clear_error()

    def show_error(self, message: str) -> None:
        self._progress_title.setText(human_state(PipelineState.FAILED))
        self._status_footer.setText(human_state(PipelineState.FAILED))
        self._error_detail.setText(message or "Unknown error")
        self._error_panel.show()

    def clear_error(self) -> None:
        self._error_panel.hide()
        self._error_detail.clear()

    def _set_stats(self, posts: int, clickbait: int, normal: int) -> None:
        self._stat_posts._value_label.setText(str(posts))  # type: ignore[attr-defined]
        self._stat_clickbait._value_label.setText(str(clickbait))  # type: ignore[attr-defined]
        self._stat_normal._value_label.setText(str(normal))  # type: ignore[attr-defined]

    def _on_run_clicked(self) -> None:
        try:
            request = self.build_request()
        except ValueError as exc:
            QMessageBox.warning(self, "Некорректный ввод", str(exc))
            return
        self.run_requested.emit(request)
