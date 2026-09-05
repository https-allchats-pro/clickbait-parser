from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QObject, QThread
from PyQt6.QtWidgets import QMessageBox

from app.gui.ml_worker import MLTrainWorker
from domain.ml import TrainingResult
from ui.main_window import MainWindow


TrainFactory = Callable[[], object]


class MLTrainController(QObject):
    """Wires MainWindow Train model button to a background MLTrainWorker."""

    def __init__(
        self,
        *,
        window: MainWindow,
        train_factory: TrainFactory,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._window = window
        self._train_factory = train_factory
        self._thread: QThread | None = None
        self._worker: MLTrainWorker | None = None

        window.ml_train_requested.connect(self.start)

    def start(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return

        self._window.set_ml_training(True)

        worker = MLTrainWorker(self._train_factory)
        thread = QThread()
        worker.moveToThread(thread)

        thread.started.connect(worker.execute)
        worker.finished.connect(self._on_finished)
        worker.error.connect(self._on_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_thread_finished)

        self._worker = worker
        self._thread = thread
        thread.start()

    def _on_finished(self, result: object) -> None:
        self._window.set_ml_training(False)
        if isinstance(result, TrainingResult):
            self._window.show_ml_train_success(result.info)
        else:
            self._window.refresh_ml_panel()

    def _on_error(self, exc: object) -> None:
        self._window.set_ml_training(False)
        message = str(exc) if exc else "Unknown error"
        QMessageBox.warning(self._window, "ML training failed", message)
        self._window.refresh_ml_panel()

    def _on_thread_finished(self) -> None:
        self._thread = None
        self._worker = None
