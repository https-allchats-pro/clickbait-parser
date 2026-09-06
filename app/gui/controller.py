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
        self._inflight_request: PipelineRequest | None = None
        self._inflight_append: bool = False
        self._inflight_target_page: int | None = None

        window.run_requested.connect(self.start)

    def start(self, request: PipelineRequest) -> None:
        # Avoid dropping load-more while the previous worker thread is still quitting.
        if self._thread is not None and self._thread.isRunning():
            self._queued_request = request
            return

        self._queued_request = None
        self._inflight_request = request
        # Stash flags up-front: thread.finished may clear inflight before the
        # queued finished slot runs, which used to force append=False and reset
        # the feed to page 1.
        self._inflight_append = bool(request.append)
        self._inflight_target_page = request.target_page
        # Soft busy for page fetch / min-views fill so the feed stays usable.
        soft = (
            bool(request.append)
            or bool(request.exclude_texts)
            or bool(getattr(self._window, "_pending_append", False))
            or bool(getattr(request, "needs_filtered_fill", False))
            or int(getattr(request, "min_views", 0) or 0) > 0
            or bool(getattr(request, "score_label", None))
            or len(getattr(self._window, "_session_queries", []) or []) > 1
            or bool(getattr(self._window, "_query_step_queue", None))
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
        append = self._inflight_append
        target_page = self._inflight_target_page
        self._inflight_append = False
        self._inflight_target_page = None
        self._window.show_result(
            result,
            append=append,
            target_page=target_page,
        )

    def _on_error(self, exc: object) -> None:
        self._inflight_append = False
        self._inflight_target_page = None
        message = str(exc) if exc else "Unknown error"
        self._window.show_error(message)

    def _on_thread_finished(self) -> None:
        self._thread = None
        self._worker = None
        self._inflight_request = None
        queued = self._queued_request
        self._queued_request = None
        if queued is not None:
            # Keep UI in the loading-more state and start the next page.
            self.start(queued)
            return
        self._window.set_running(False)
