from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from app.auth.models import VKProfile

logger = logging.getLogger(__name__)

StatusCallback = Callable[[str], None]
QrCallback = Callable[[str], None]


class AuthRunner(Protocol):
    def login_vk(self, *, method: str = "qr") -> VKProfile: ...


class AuthFactory(Protocol):
    def __call__(
        self,
        *,
        on_status: StatusCallback | None = None,
        on_qr: QrCallback | None = None,
    ) -> AuthRunner: ...


class AuthWorker(QObject):
    """Runs QR login off the GUI thread; emits QR URL for in-app display."""

    finished = pyqtSignal(object)
    error = pyqtSignal(object)
    status = pyqtSignal(str)
    qr_ready = pyqtSignal(str)

    def __init__(self, auth_factory: AuthFactory, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._auth_factory = auth_factory

    @pyqtSlot()
    def execute(self) -> None:
        try:
            self.status.emit("Получение QR-кода…")
            auth = self._auth_factory(
                on_status=self._on_status,
                on_qr=self._on_qr,
            )
            profile = auth.login_vk(method="qr")
        except Exception as exc:
            logger.exception("profile auth failed")
            self.error.emit(exc)
            return
        self.finished.emit(profile)

    def _on_status(self, message: str) -> None:
        # Skip huge ASCII QR dumps — GUI shows a pixmap instead.
        if message.count("\n") > 5 or len(message) > 400:
            return
        self.status.emit(message)

    def _on_qr(self, auth_url: str) -> None:
        self.qr_ready.emit(auth_url)
