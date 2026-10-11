from __future__ import annotations

import sys

from PyQt6.QtCore import QObject, Qt, QThread
from PyQt6.QtWidgets import QApplication, QMessageBox, QProgressDialog, QWidget

from app.gui.update_worker import (
    ManagerFactory,
    UpdateCheckWorker,
    UpdateDownloadWorker,
)


def velopack_manager_factory(repo_url: str) -> ManagerFactory:
    def factory() -> object:
        import velopack

        return velopack.UpdateManager(velopack.GithubSource(repo_url))

    return factory


class UpdateController(QObject):
    """Checks GitHub Releases via Velopack, asks the user, downloads and restarts."""

    def __init__(
        self,
        *,
        window: QWidget,
        manager_factory: ManagerFactory,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._window = window
        self._manager_factory = manager_factory
        # Check and download threads may briefly overlap while the dialog is open.
        self._running: dict[QThread, QObject] = {}
        self._busy = False
        self._progress: QProgressDialog | None = None
        self._pending: object | None = None

    def check(self) -> None:
        if self._busy:
            return
        self._busy = True
        worker = UpdateCheckWorker(self._manager_factory)
        worker.finished.connect(self._on_check_finished)
        worker.error.connect(self._on_check_error)
        self._start(worker)

    def _start(self, worker: QObject) -> None:
        thread = QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.execute)  # type: ignore[attr-defined]
        worker.finished.connect(thread.quit)  # type: ignore[attr-defined]
        worker.error.connect(thread.quit)  # type: ignore[attr-defined]
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda: self._running.pop(thread, None))
        self._running[thread] = worker
        thread.start()

    def _on_check_error(self, _exc: object) -> None:
        self._busy = False

    def _on_check_finished(self, info: object) -> None:
        if info is not None and self._ask_user(info):
            self._download(info)
            return
        self._busy = False

    def _ask_user(self, info: object) -> bool:
        target = info.TargetFullRelease  # type: ignore[attr-defined]
        box = QMessageBox(self._window)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Доступно обновление")
        current = self._current_version()
        suffix = f" (у вас {current})" if current else ""
        box.setText(f"Доступна новая версия {target.Version}{suffix}.\nОбновить сейчас?")
        if target.NotesMarkdown:
            box.setDetailedText(target.NotesMarkdown)
        update_btn = box.addButton("Обновить", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Позже", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(update_btn)
        box.exec()
        return box.clickedButton() is update_btn

    def _current_version(self) -> str | None:
        try:
            return self._manager_factory().get_current_version()  # type: ignore[attr-defined]
        except Exception:
            return None

    def _download(self, info: object) -> None:
        progress = QProgressDialog("Загрузка обновления…", None, 0, 100, self._window)
        progress.setWindowTitle("Обновление")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setValue(0)
        self._progress = progress
        self._pending = info

        worker = UpdateDownloadWorker(self._manager_factory, info)
        worker.progress.connect(progress.setValue)
        worker.finished.connect(self._on_download_finished)
        worker.error.connect(self._on_download_error)
        self._start(worker)

    def _on_download_finished(self) -> None:
        self._close_progress()
        try:
            self._manager_factory().apply_updates_and_restart(self._pending)  # type: ignore[attr-defined]
        except Exception as exc:
            self._busy = False
            QMessageBox.warning(self._window, "Обновление", f"Не удалось установить обновление:\n{exc}")
            return
        QApplication.quit()

    def _on_download_error(self, exc: object) -> None:
        self._busy = False
        self._close_progress()
        QMessageBox.warning(self._window, "Обновление", f"Не удалось скачать обновление:\n{exc}")

    def _close_progress(self) -> None:
        if self._progress is not None:
            self._progress.close()
            self._progress = None


def maybe_start_update_check(window: QWidget, *, repo_url: str | None) -> UpdateController | None:
    """Start a background check in frozen builds that know their release repo."""
    if not repo_url or not getattr(sys, "frozen", False):
        return None
    controller = UpdateController(
        window=window,
        manager_factory=velopack_manager_factory(repo_url),
        parent=window,
    )
    controller.check()
    return controller
