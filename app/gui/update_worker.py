from __future__ import annotations

import logging
from collections.abc import Callable

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

logger = logging.getLogger(__name__)

ManagerFactory = Callable[[], object]


class UpdateCheckWorker(QObject):
    """Runs ``UpdateManager.check_for_updates()`` off the GUI thread."""

    finished = pyqtSignal(object)  # velopack.UpdateInfo | None
    error = pyqtSignal(object)

    def __init__(
        self,
        manager_factory: ManagerFactory,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._manager_factory = manager_factory

    @pyqtSlot()
    def execute(self) -> None:
        try:
            info = self._manager_factory().check_for_updates()  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning("update check failed: %s", exc)
            self.error.emit(exc)
            return
        self.finished.emit(info)


class UpdateDownloadWorker(QObject):
    """Downloads a pending update; reports progress in percent (0..100)."""

    progress = pyqtSignal(int)
    finished = pyqtSignal()
    error = pyqtSignal(object)

    def __init__(
        self,
        manager_factory: ManagerFactory,
        update_info: object,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._manager_factory = manager_factory
        self._update_info = update_info

    @pyqtSlot()
    def execute(self) -> None:
        try:
            manager = self._manager_factory()
            manager.download_updates(  # type: ignore[attr-defined]
                self._update_info,
                lambda percent: self.progress.emit(int(percent)),
            )
        except Exception as exc:
            logger.exception("update download failed")
            self.error.emit(exc)
            return
        self.finished.emit()
