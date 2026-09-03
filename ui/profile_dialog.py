from __future__ import annotations

from typing import Protocol

from PyQt6.QtCore import Qt, QThread
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app.auth.models import VKProfile
from app.gui.auth_worker import AuthFactory, AuthWorker
from infrastructure.vk.qr_display import render_qr_png_bytes


class ProfileStore(Protocol):
    def get_profiles(self) -> list[VKProfile]: ...

    def logout(self, profile_id: int) -> None: ...


def format_profile_label(profile: VKProfile) -> str:
    name = " ".join(
        part for part in (profile.first_name, profile.last_name) if part
    ).strip()
    name = name or "(без имени)"
    return f"#{profile.id}  {name}  ·  vk:{profile.provider_user_id}"


class ProfileSelectDialog(QDialog):
    """Choose VK profile before opening the main window. + add (QR), − remove."""

    def __init__(
        self,
        *,
        profiles: ProfileStore,
        auth_factory: AuthFactory,
        initial_profile_id: int | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Выбор профиля")
        self.resize(560, 520)
        self.setModal(True)

        self._profiles = profiles
        self._auth_factory = auth_factory
        self._selected_id: int | None = None
        self._auth_thread: QThread | None = None
        self._auth_worker: AuthWorker | None = None

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._accept_if_selected)
        self._list.currentItemChanged.connect(lambda *_: self._update_buttons())

        self._status = QLabel("Выберите профиль VK или добавьте новый.")
        self._status.setWordWrap(True)

        self._qr_label = QLabel()
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setMinimumSize(280, 280)
        self._qr_label.setStyleSheet(
            "QLabel { background: #ffffff; border: 1px solid #d0d7de; border-radius: 8px; }"
        )
        self._qr_label.hide()
        self._qr_hint = QLabel("Отсканируйте QR в приложении VK на телефоне")
        self._qr_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_hint.setWordWrap(True)
        self._qr_hint.hide()

        self._btn_add = QPushButton("+")
        self._btn_add.setToolTip("Добавить профиль (QR)")
        self._btn_add.clicked.connect(self._on_add)

        self._btn_remove = QPushButton("−")
        self._btn_remove.setToolTip("Удалить выбранный профиль")
        self._btn_remove.clicked.connect(self._on_remove)

        side = QVBoxLayout()
        side.addWidget(self._btn_add)
        side.addWidget(self._btn_remove)
        side.addStretch(1)

        list_row = QHBoxLayout()
        list_row.addWidget(self._list, stretch=1)
        list_row.addLayout(side)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        assert self._ok_button is not None
        self._ok_button.setText("Продолжить")
        buttons.accepted.connect(self._accept_if_selected)
        buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addWidget(QLabel("Профиль для анализа"))
        root.addLayout(list_row, stretch=1)
        root.addWidget(self._qr_hint)
        root.addWidget(self._qr_label, alignment=Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._status)
        root.addWidget(buttons)

        self.reload(select_id=initial_profile_id)

    @property
    def selected_profile_id(self) -> int | None:
        return self._selected_id

    def reload(self, *, select_id: int | None = None) -> None:
        prefer = select_id if select_id is not None else self._current_profile_id()
        self._list.clear()
        rows = [p for p in self._profiles.get_profiles() if p.provider == "vk"]
        target_row = 0
        for index, profile in enumerate(rows):
            item = QListWidgetItem(format_profile_label(profile))
            item.setData(Qt.ItemDataRole.UserRole, profile.id)
            self._list.addItem(item)
            if prefer is not None and profile.id == prefer:
                target_row = index
        if self._list.count() > 0:
            self._list.setCurrentRow(target_row)
        self._update_buttons()
        if self._list.count() == 0:
            self._status.setText("Профилей нет. Нажмите «+», чтобы войти через QR.")

    def show_qr(self, auth_url: str) -> None:
        png = render_qr_png_bytes(auth_url, box_size=8, border=2)
        pixmap = QPixmap()
        ok = pixmap.loadFromData(png, "PNG")
        if not ok:
            self._status.setText("Не удалось отрисовать QR-код")
            return
        self._qr_label.setPixmap(
            pixmap.scaled(
                280,
                280,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self._qr_label.show()
        self._qr_hint.show()
        self._status.setText("Отсканируйте QR-код в приложении VK")

    def clear_qr(self) -> None:
        self._qr_label.clear()
        self._qr_label.hide()
        self._qr_hint.hide()

    def _current_profile_id(self) -> int | None:
        item = self._list.currentItem()
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return int(value) if value is not None else None

    def _update_buttons(self) -> None:
        has_selection = self._current_profile_id() is not None
        busy = self._auth_thread is not None and self._auth_thread.isRunning()
        self._ok_button.setEnabled(has_selection and not busy)
        self._btn_remove.setEnabled(has_selection and not busy)
        self._btn_add.setEnabled(not busy)
        self._list.setEnabled(not busy)

    def _accept_if_selected(self) -> None:
        profile_id = self._current_profile_id()
        if profile_id is None:
            QMessageBox.information(self, "Профиль", "Сначала выберите профиль.")
            return
        self._selected_id = profile_id
        self.accept()

    def _on_remove(self) -> None:
        profile_id = self._current_profile_id()
        if profile_id is None:
            return
        item = self._list.currentItem()
        label = item.text() if item is not None else str(profile_id)
        answer = QMessageBox.question(
            self,
            "Удалить профиль",
            f"Удалить профиль и сохранённый токен?\n\n{label}",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._profiles.logout(profile_id)
        except Exception as exc:
            QMessageBox.warning(self, "Ошибка", str(exc))
            return
        self._status.setText(f"Профиль #{profile_id} удалён.")
        self.reload()

    def _on_add(self) -> None:
        if self._auth_thread is not None and self._auth_thread.isRunning():
            return

        self.clear_qr()
        self._status.setText("Идёт авторизация по QR…")
        worker = AuthWorker(self._auth_factory)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.execute)
        worker.status.connect(self._status.setText)
        worker.qr_ready.connect(self.show_qr)
        worker.finished.connect(self._on_auth_finished)
        worker.error.connect(self._on_auth_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_auth_thread_finished)

        self._auth_worker = worker
        self._auth_thread = thread
        self._update_buttons()
        thread.start()

    def _on_auth_finished(self, profile: object) -> None:
        self.clear_qr()
        if not isinstance(profile, VKProfile) or profile.id is None:
            self._status.setText("Авторизация завершена, но профиль не сохранён.")
            return
        self._status.setText(f"Добавлен: {format_profile_label(profile)}")
        self.reload(select_id=profile.id)

    def _on_auth_error(self, exc: object) -> None:
        self.clear_qr()
        message = str(exc) if exc else "Неизвестная ошибка"
        self._status.setText("Не удалось добавить профиль.")
        QMessageBox.warning(self, "Авторизация", message)

    def _on_auth_thread_finished(self) -> None:
        self._auth_thread = None
        self._auth_worker = None
        self._update_buttons()
