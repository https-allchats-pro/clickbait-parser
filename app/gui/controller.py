from __future__ import annotations

from PyQt6.QtCore import QObject, Qt, QThread

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
        self._queued_request: PipelineRequest | None = None

        window.run_requested.connect(self.start)

    def start(self, request: PipelineRequest) -> None:
        # Avoid dropping load-more while the previous worker thread is still quitting.
        if self._thread is not None and self._thread.isRunning():
            self._queued_request = request
            return

        self._queued_request = None
        # Soft busy for infinite-scroll / min-views fill so the feed stays usable.
        soft = (
            bool(request.exclude_texts)
            or bool(getattr(self._window, "_pending_append", False))
            or int(getattr(request, "min_views", 0) or 0) > 0
        )
        self._window.set_running(True, soft=soft)
        if not soft:
            self._window.clear_error()

        worker = PipelineWorker(self._pipeline_factory)
        worker.set_request(request)
        thread = QThread()
        worker.moveToThread(thread)

        thread.started.connect(worker.execute)
        # Cross-thread UI updates stay queued so the GUI event loop can paint.
        worker.progress.connect(self._on_progress, Qt.ConnectionType.QueuedConnection)
        worker.finished.connect(self._on_finished, Qt.ConnectionType.QueuedConnection)
        worker.error.connect(self._on_error, Qt.ConnectionType.QueuedConnection)
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

    def _on_error(self, exc: object) -> None:
        message = str(exc) if exc else "Unknown error"
        self._window.show_error(message)

    def _on_thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        queued = self._queued_request
        self._queued_request = None
        if queued is not None:
            # Keep UI in the loading-more state and start the next page.
            self.start(queued)
            return
        self._window.set_running(False)
