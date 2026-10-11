from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QCoreApplication, QElapsedTimer
from PyQt6.QtWidgets import QApplication, QWidget

from app.gui.update_controller import UpdateController, maybe_start_update_check
from app.gui.update_worker import UpdateCheckWorker, UpdateDownloadWorker

_APP = QApplication.instance() or QApplication(["clickbait-parser-tests"])


def _update_info(version: str = "0.2.0") -> SimpleNamespace:
    return SimpleNamespace(
        TargetFullRelease=SimpleNamespace(Version=version, NotesMarkdown="")
    )


class FakeManager:
    def __init__(self, info: object | None = None, *, fail_check: bool = False) -> None:
        self.info = info
        self.fail_check = fail_check
        self.downloaded: list[object] = []
        self.applied: list[object] = []

    def check_for_updates(self) -> object | None:
        if self.fail_check:
            raise RuntimeError("This application is not properly installed")
        return self.info

    def get_current_version(self) -> str:
        return "0.1.0"

    def download_updates(self, info: object, progress_callback=None) -> None:
        for percent in (0, 50, 100):
            if progress_callback is not None:
                progress_callback(percent)
        self.downloaded.append(info)

    def apply_updates_and_restart(self, info: object) -> None:
        self.applied.append(info)


def _wait_until(predicate, timeout_ms: int = 3000) -> bool:
    timer = QElapsedTimer()
    timer.start()
    while not predicate():
        if timer.elapsed() > timeout_ms:
            return False
        QCoreApplication.processEvents()
    return True


class UpdateWorkerTests(unittest.TestCase):
    def test_check_worker_emits_update_info(self) -> None:
        info = _update_info()
        worker = UpdateCheckWorker(lambda: FakeManager(info))
        got: list[object] = []
        worker.finished.connect(got.append)
        worker.execute()
        self.assertEqual(got, [info])

    def test_check_worker_reports_not_installed_as_error(self) -> None:
        worker = UpdateCheckWorker(lambda: FakeManager(fail_check=True))
        errors: list[object] = []
        worker.error.connect(errors.append)
        worker.execute()
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)

    def test_download_worker_forwards_progress(self) -> None:
        manager = FakeManager()
        info = _update_info()
        worker = UpdateDownloadWorker(lambda: manager, info)
        progress: list[int] = []
        done: list[bool] = []
        worker.progress.connect(progress.append)
        worker.finished.connect(lambda: done.append(True))
        worker.execute()
        self.assertEqual(progress, [0, 50, 100])
        self.assertEqual(done, [True])
        self.assertEqual(manager.downloaded, [info])


class UpdateControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.window = QWidget()

    def tearDown(self) -> None:
        self.window.deleteLater()

    def test_accepting_update_downloads_and_applies(self) -> None:
        info = _update_info()
        manager = FakeManager(info)
        controller = UpdateController(window=self.window, manager_factory=lambda: manager)
        with (
            mock.patch.object(UpdateController, "_ask_user", return_value=True),
            mock.patch("app.gui.update_controller.QApplication.quit") as quit_app,
        ):
            controller.check()
            self.assertTrue(_wait_until(lambda: bool(manager.applied)))
            _wait_until(lambda: not controller._running)
        self.assertEqual(manager.downloaded, [info])
        self.assertEqual(manager.applied, [info])
        quit_app.assert_called_once()

    def test_declining_update_skips_download(self) -> None:
        manager = FakeManager(_update_info())
        controller = UpdateController(window=self.window, manager_factory=lambda: manager)
        with mock.patch.object(UpdateController, "_ask_user", return_value=False) as ask:
            controller.check()
            self.assertTrue(_wait_until(lambda: ask.called and not controller._running))
        self.assertEqual(manager.downloaded, [])
        self.assertFalse(controller._busy)

    def test_no_update_does_not_prompt(self) -> None:
        manager = FakeManager(None)
        controller = UpdateController(window=self.window, manager_factory=lambda: manager)
        with mock.patch.object(UpdateController, "_ask_user") as ask:
            controller.check()
            self.assertTrue(_wait_until(lambda: not controller._busy and not controller._running))
        ask.assert_not_called()


class MaybeStartUpdateCheckTests(unittest.TestCase):
    def test_disabled_outside_frozen_build(self) -> None:
        self.assertIsNone(maybe_start_update_check(QWidget(), repo_url="https://github.com/o/r"))

    def test_disabled_without_repo_url(self) -> None:
        with mock.patch("sys.frozen", True, create=True):
            self.assertIsNone(maybe_start_update_check(QWidget(), repo_url=None))


if __name__ == "__main__":
    unittest.main()
