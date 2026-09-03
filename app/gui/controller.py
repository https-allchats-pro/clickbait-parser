from __future__ import annotations

from PyQt6.QtCore import QObject, QThread

from app.gui.worker import PipelineFactory, PipelineWorker
from domain.pipeline import PipelineProgress, PipelineRequest, PipelineResult
from ui.main_window import MainWindow


class PipelineController(QObject):
    """Wires MainWindow signals to a background PipelineWorker."""

    def __init__(
        self,
        *,
        window: MainWindow,
        pipeline_factory: PipelineFactory,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._window = window
        self._pipeline_factory = pipeline_factory
        self._thread: QThread | None = None
        self._worker: PipelineWorker | None = None

        window.run_requested.connect(self.start)

    def start(self, request: PipelineRequest) -> None:
        if self._thread is not None and self._thread.isRunning():
            return

        self._window.set_running(True)
        self._window.clear_error()

        worker = PipelineWorker(self._pipeline_factory)
        worker.set_request(request)
        thread = QThread()
        worker.moveToThread(thread)

        thread.started.connect(worker.execute)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_finished)
        worker.error.connect(self._on_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_thread_finished)

        self._worker = worker
        self._thread = thread
        thread.start()

    def _on_progress(self, progress: PipelineProgress) -> None:
        self._window.apply_progress(progress)

    def _on_finished(self, result: PipelineResult) -> None:
        self._window.show_result(result)
        self._window.set_running(False)

    def _on_error(self, exc: object) -> None:
        message = str(exc) if exc else "Unknown error"
        self._window.show_error(message)
        self._window.set_running(False)

    def _on_thread_finished(self) -> None:
        self._thread = None
        self._worker = None
