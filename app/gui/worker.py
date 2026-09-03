from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from domain.pipeline import PipelineProgress, PipelineRequest, PipelineResult

logger = logging.getLogger(__name__)


class RunnablePipeline(Protocol):
    def run(
        self,
        request: PipelineRequest,
        *,
        on_progress=None,
    ) -> PipelineResult: ...


PipelineFactory = Callable[[], RunnablePipeline]


class PipelineWorker(QObject):
    """Runs ClickbaitPipeline off the GUI thread; adapts progress to Qt signals.

    Pipeline is built via ``pipeline_factory`` *inside* ``execute()`` so SQLite
    connections are created on the same thread that uses them.
    """

    progress = pyqtSignal(object)
    finished = pyqtSignal(object)
    error = pyqtSignal(object)

    def __init__(
        self,
        pipeline_factory: PipelineFactory,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._pipeline_factory = pipeline_factory
        self._request: PipelineRequest | None = None

    def set_request(self, request: PipelineRequest) -> None:
        self._request = request

    @pyqtSlot()
    def execute(self) -> None:
        request = self._request
        if request is None:
            self.error.emit(ValueError("PipelineWorker: request is not set"))
            return
        try:
            # Build on the worker thread (not the GUI thread).
            pipeline = self._pipeline_factory()
            result = pipeline.run(request, on_progress=self._on_progress)
        except Exception as exc:
            logger.exception("pipeline failed in worker")
            self.error.emit(exc)
            return
        self.finished.emit(result)

    def _on_progress(self, progress: PipelineProgress) -> None:
        self.progress.emit(progress)
