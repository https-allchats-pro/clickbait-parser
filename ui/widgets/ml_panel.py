from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from domain.ml import ModelInfo
from ui.theme import SP_8, SP_12, SP_16


class MLModelPanel(QFrame):
    """ML model status + Train button (presentation only)."""

    train_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")

        title = QLabel("ML Model")
        title.setObjectName("sectionLabel")

        self._status = QLabel("Status: Not trained")
        self._status.setObjectName("metaLabel")
        self._status.setWordWrap(True)

        self._detail = QLabel("")
        self._detail.setObjectName("statusFooter")
        self._detail.setWordWrap(True)

        self._dataset = QLabel("")
        self._dataset.setObjectName("statusFooter")
        self._dataset.setWordWrap(True)

        self._new_labels = QLabel("")
        self._new_labels.setObjectName("statusFooter")
        self._new_labels.setWordWrap(True)
        self._new_labels.hide()

        self._train_button = QPushButton("Train ML")
        self._train_button.setObjectName("primaryButton")
        self._train_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._train_button.clicked.connect(self.train_requested.emit)

        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self._train_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SP_16, SP_12, SP_16, SP_12)
        layout.setSpacing(SP_8)
        layout.addLayout(header)
        layout.addWidget(self._status)
        layout.addWidget(self._dataset)
        layout.addWidget(self._detail)
        layout.addWidget(self._new_labels)

    def set_training(self, training: bool) -> None:
        self._train_button.setEnabled(not training)
        if training:
            self._train_button.setText("Training...")
            self._status.setText("Status: Training…")
        else:
            self._train_button.setText("Train ML")

    def show_not_trained(
        self,
        *,
        labeled_binary: int = 0,
        dataset_total: int = 0,
    ) -> None:
        self._status.setText("Status: Not trained")
        total = dataset_total or labeled_binary
        self._dataset.setText(f"Dataset: {total:,} posts")
        self._detail.setText(
            "Train TF-IDF + Logistic Regression on human CLICKBAIT / NORMAL labels."
        )
        if labeled_binary > 0:
            self._new_labels.setText(
                f"{labeled_binary} labeled posts ready for first training"
            )
            self._new_labels.show()
        else:
            self._new_labels.hide()
        self._train_button.setText("Train ML")

    def show_model_info(
        self,
        info: ModelInfo,
        *,
        new_labels: int = 0,
        dataset_total: int = 0,
        clickbait: int = 0,
        normal: int = 0,
    ) -> None:
        m = info.metrics
        when = info.trained_at.astimezone().strftime("%Y-%m-%d %H:%M")
        self._status.setText(f"Status: Trained  ·  Version v{info.version}")
        total = dataset_total or (m.clickbait_samples + m.normal_samples)
        cb = clickbait or m.clickbait_samples
        nm = normal or m.normal_samples
        self._dataset.setText(
            f"Dataset: {total:,} posts\n"
            f"Clickbait: {cb:,}\n"
            f"Not clickbait: {nm:,}"
        )
        self._detail.setText(
            f"Last trained: {when}\n"
            f"F1 {m.f1 * 100:.1f}%  ·  Acc {m.accuracy * 100:.1f}%  ·  "
            f"train {m.train_samples} / test {m.test_samples}"
        )
        if new_labels > 0:
            self._new_labels.setText(
                f"{new_labels} new labels since last training — consider retrain"
            )
            self._new_labels.show()
            self._train_button.setText("Retrain ML")
        else:
            self._new_labels.hide()
            self._train_button.setText("Train ML")

    def show_train_success(self, info: ModelInfo) -> None:
        m = info.metrics
        when = info.trained_at.astimezone().strftime("%Y-%m-%d %H:%M")
        self._status.setText(
            f"Status: Trained  ·  Version v{info.version}  ·  F1 {m.f1 * 100:.1f}%"
        )
        self._detail.setText(f"Last trained: {when}")
        self._new_labels.hide()
        self._train_button.setText("Train ML")
        self._train_button.setEnabled(True)
