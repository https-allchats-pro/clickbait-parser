from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QFormLayout,
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
from ui.widgets.results_view import ResultsView


class MainWindow(QMainWindow):
    """Presentation shell: inputs, progress, results. No VK/SQLite/pipeline logic."""

    run_requested = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("clickbait-parser")
        self.resize(720, 800)

        self._query_input = QLineEdit()
        self._query_input.setPlaceholderText("опционально, например: новости")

        self._limit_input = QSpinBox()
        self._limit_input.setMinimum(1)
        self._limit_input.setMaximum(10_000)
        self._limit_input.setValue(100)

        self._run_button = QPushButton("Запустить анализ")
        self._run_button.clicked.connect(self._on_run_clicked)

        form = QFormLayout()
        form.addRow("Query", self._query_input)
        form.addRow("Limit", self._limit_input)

        input_row = QHBoxLayout()
        input_row.addLayout(form, stretch=1)
        input_row.addWidget(self._run_button)

        self._state_label = QLabel("State: idle")
        self._progress_label = QLabel("Progress: —")
        self._progress_bar = QProgressBar()
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)

        self._error_label = QLabel()
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet("color: #b00020;")
        self._error_label.hide()

        self._results = ResultsView()

        root = QVBoxLayout()
        root.addLayout(input_row)
        root.addWidget(self._state_label)
        root.addWidget(self._progress_label)
        root.addWidget(self._progress_bar)
        root.addWidget(self._error_label)
        root.addWidget(self._results, stretch=1)

        container = QWidget()
        container.setLayout(root)
        self.setCentralWidget(container)

        self._controller: object | None = None

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
        if running:
            self._run_button.setText("Анализ выполняется...")
            self.clear_error()
        else:
            self._run_button.setText("Запустить анализ")

    def apply_progress(self, progress: PipelineProgress) -> None:
        self._state_label.setText(f"State: {progress.state.value.upper()}")
        total = max(0, int(progress.total))
        current = max(0, int(progress.current))
        if total > 0:
            self._progress_bar.setMaximum(total)
            self._progress_bar.setValue(min(current, total))
            self._progress_label.setText(f"Progress: {current} / {total}")
        else:
            self._progress_bar.setMaximum(1)
            self._progress_bar.setValue(0 if progress.state != PipelineState.COMPLETED else 1)
            self._progress_label.setText(f"Progress: {current} / {total}")

    def show_result(self, result: PipelineResult) -> None:
        self._state_label.setText(f"State: {PipelineState.COMPLETED.value.upper()}")
        total = max(result.analyzed, len(result.posts))
        self._progress_bar.setMaximum(max(total, 1))
        self._progress_bar.setValue(total if total else 1)
        self._progress_label.setText(f"Progress: {total} / {total}")
        self._results.set_results(result.posts)

    def show_error(self, message: str) -> None:
        self._state_label.setText(f"State: {PipelineState.FAILED.value.upper()}")
        self._error_label.setText(
            "Не удалось выполнить анализ.\n" + (message or "Unknown error")
        )
        self._error_label.show()

    def clear_error(self) -> None:
        self._error_label.hide()
        self._error_label.clear()

    def _on_run_clicked(self) -> None:
        try:
            request = self.build_request()
        except ValueError as exc:
            QMessageBox.warning(self, "Некорректный ввод", str(exc))
            return
        self.run_requested.emit(request)
