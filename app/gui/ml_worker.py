from __future__ import annotations

import logging
from collections.abc import Callable

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from domain.ml import TrainingResult

logger = logging.getLogger(__name__)

TrainFactory = Callable[[], object]


class MLTrainWorker(QObject):
    """Runs ``MLTrainingService.train()`` off the GUI thread."""

    finished = pyqtSignal(object)  # TrainingResult
    error = pyqtSignal(object)

    def __init__(
        self,
        train_factory: TrainFactory,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._train_factory = train_factory

    @pyqtSlot()
    def execute(self) -> None:
        try:
            service = self._train_factory()
            result = service.train()  # type: ignore[attr-defined]
        except Exception as exc:
            logger.exception("ML training failed in worker")
            self.error.emit(exc)
            return
        if not isinstance(result, TrainingResult):
            self.error.emit(TypeError("train() did not return TrainingResult"))
            return
        self.finished.emit(result)
