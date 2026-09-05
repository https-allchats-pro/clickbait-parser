from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.ml.feature_insights import (
    DEFAULT_TOP_N,
    ModelFeature,
    ModelInsightsError,
    ModelInsightsService,
)
from domain.ml import MLModelNotFoundError, ModelInfo
from ui.theme import SP_4, SP_8, SP_12, SP_16


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _format_trained_at(info: ModelInfo) -> str:
    when = info.trained_at.astimezone()
    return f"{when.day} {when.strftime('%b %Y, %H:%M')}"


class _FeatureRow(QFrame):
    """Compact term + strength bar + coefficient."""

    def __init__(
        self,
        feature: ModelFeature,
        *,
        kind: str,
        max_abs: float,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("featureRow")

        term = QLabel(f'"{feature.term}"')
        term.setObjectName("featureTerm")
        term.setWordWrap(False)
        term.setMinimumWidth(120)

        bar = QProgressBar()
        bar.setTextVisible(False)
        bar.setFixedHeight(8)
        bar.setMinimum(0)
        bar.setMaximum(1000)
        strength = abs(float(feature.coefficient))
        fill = int(round(1000 * strength / max_abs)) if max_abs > 0 else 0
        bar.setValue(min(max(fill, 0), 1000))
        bar.setObjectName(
            "featureBarClickbait" if kind == "clickbait" else "featureBarNormal"
        )

        sign = "+" if feature.coefficient >= 0 else ""
        coef = QLabel(f"{sign}{feature.coefficient:.2f}")
        coef.setObjectName(
            "featureCoefClickbait" if kind == "clickbait" else "featureCoefNormal"
        )
        coef.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        coef.setFixedWidth(64)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, SP_4, 0, SP_4)
        layout.setSpacing(SP_8)
        layout.addWidget(term, stretch=2)
        layout.addWidget(bar, stretch=3)
        layout.addWidget(coef, stretch=0)

        cls = "CLICKBAIT" if kind == "clickbait" else "NORMAL"
        tip = (
            f"TF-IDF feature\n\n"
            f"Coefficient: {sign}{feature.coefficient:.2f}\n"
            f"Class: {cls}"
        )
        self.setToolTip(tip)
        term.setToolTip(tip)
        bar.setToolTip(tip)
        coef.setToolTip(tip)


class ModelInsightsView(QWidget):
    """Presentation for model metrics + top TF-IDF / LogReg features."""

    train_requested = pyqtSignal()

    def __init__(
        self,
        *,
        top_n: int = DEFAULT_TOP_N,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._top_n = max(1, int(top_n))
        self._service: ModelInsightsService | None = None

        title = QLabel("Model Insights")
        title.setObjectName("insightsTitle")

        # --- empty state ---
        empty_title = QLabel("No trained model available.")
        empty_title.setObjectName("emptyTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_hint = QLabel("Train a model to see model insights.")
        empty_hint.setObjectName("emptyHint")
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_hint.setWordWrap(True)
        self._empty_train = QPushButton("Train model")
        self._empty_train.setObjectName("primaryButton")
        self._empty_train.setCursor(Qt.CursorShape.PointingHandCursor)
        self._empty_train.clicked.connect(self.train_requested.emit)

        empty_inner = QVBoxLayout()
        empty_inner.setSpacing(SP_12)
        empty_inner.addStretch(1)
        empty_inner.addWidget(empty_title)
        empty_inner.addWidget(empty_hint)
        empty_inner.addWidget(self._empty_train, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_inner.addStretch(1)
        empty_page = QFrame()
        empty_page.setObjectName("panel")
        empty_page.setLayout(empty_inner)

        # --- content state ---
        self._algo = QLabel("TF-IDF + Logistic Regression")
        self._algo.setObjectName("insightsAlgo")
        self._version = QLabel("")
        self._version.setObjectName("metaLabel")
        self._trained = QLabel("")
        self._trained.setObjectName("metaLabel")
        self._samples = QLabel("")
        self._samples.setObjectName("metaLabel")
        self._class_counts = QLabel("")
        self._class_counts.setObjectName("metaLabel")

        self._metric_acc = self._metric_chip("Accuracy", "—")
        self._metric_prec = self._metric_chip("Precision", "—")
        self._metric_rec = self._metric_chip("Recall", "—")
        self._metric_f1 = self._metric_chip("F1", "—")

        metrics_row = QHBoxLayout()
        metrics_row.setSpacing(SP_12)
        for chip in (
            self._metric_acc,
            self._metric_prec,
            self._metric_rec,
            self._metric_f1,
        ):
            metrics_row.addWidget(chip, stretch=1)

        summary = QFrame()
        summary.setObjectName("panel")
        summary_layout = QVBoxLayout(summary)
        summary_layout.setContentsMargins(SP_16, SP_16, SP_16, SP_16)
        summary_layout.setSpacing(SP_8)
        summary_head = QLabel("Current model")
        summary_head.setObjectName("sectionLabel")
        summary_layout.addWidget(summary_head)
        summary_layout.addWidget(self._algo)
        summary_layout.addWidget(self._version)
        summary_layout.addWidget(self._trained)
        summary_layout.addWidget(self._samples)
        summary_layout.addWidget(self._class_counts)
        summary_layout.addSpacing(SP_8)
        summary_layout.addLayout(metrics_row)

        self._clickbait_list = QVBoxLayout()
        self._clickbait_list.setSpacing(SP_4)
        self._normal_list = QVBoxLayout()
        self._normal_list.setSpacing(SP_4)

        clickbait_panel = self._feature_panel("CLICKBAIT", self._clickbait_list)
        normal_panel = self._feature_panel("NORMAL", self._normal_list)

        features_row = QHBoxLayout()
        features_row.setSpacing(SP_16)
        features_row.addWidget(clickbait_panel, stretch=1)
        features_row.addWidget(normal_panel, stretch=1)

        how = QLabel(
            "How to read this\n\n"
            "Features with a positive coefficient are associated with CLICKBAIT.\n"
            "Features with a negative coefficient are associated with NORMAL posts.\n"
            "A larger absolute coefficient means a stronger influence on the model's "
            "decision."
        )
        how.setObjectName("insightsHowTo")
        how.setWordWrap(True)

        self._last_trained = QLabel("")
        self._last_trained.setObjectName("statusFooter")

        content_inner = QVBoxLayout()
        content_inner.setContentsMargins(0, 0, 0, 0)
        content_inner.setSpacing(SP_16)
        content_inner.addWidget(summary)
        content_inner.addLayout(features_row)
        content_inner.addWidget(how)
        content_inner.addWidget(self._last_trained)
        content_inner.addStretch(1)

        content_host = QWidget()
        content_host.setLayout(content_inner)
        content_host.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content_host)
        self._content_page = scroll

        self._stack = QStackedWidget()
        self._stack.addWidget(empty_page)
        self._stack.addWidget(self._content_page)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SP_16)
        root.addWidget(title)
        root.addWidget(self._stack, stretch=1)

        self._stack.setCurrentIndex(0)

    @staticmethod
    def _metric_chip(caption: str, value: str) -> QFrame:
        chip = QFrame()
        chip.setObjectName("statCard")
        value_label = QLabel(value)
        value_label.setObjectName("statValue")
        caption_label = QLabel(caption)
        caption_label.setObjectName("statCaption")
        layout = QVBoxLayout(chip)
        layout.setContentsMargins(SP_12, SP_8, SP_12, SP_8)
        layout.setSpacing(SP_4)
        layout.addWidget(value_label)
        layout.addWidget(caption_label)
        chip._value_label = value_label  # type: ignore[attr-defined]
        return chip

    @staticmethod
    def _feature_panel(title: str, body: QVBoxLayout) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panel")
        head = QLabel(title)
        head.setObjectName("sectionLabel")
        if title == "CLICKBAIT":
            head.setObjectName("insightsClickbaitHead")
        else:
            head.setObjectName("insightsNormalHead")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(SP_16, SP_16, SP_16, SP_16)
        layout.setSpacing(SP_8)
        layout.addWidget(head)
        layout.addLayout(body)
        layout.addStretch(1)
        return panel

    def set_service(self, service: ModelInsightsService | None) -> None:
        self._service = service
        self.refresh()

    def set_training(self, training: bool) -> None:
        self._empty_train.setEnabled(not training)
        if training:
            self._empty_train.setText("Training...")
        else:
            self._empty_train.setText("Train model")

    def refresh(self) -> None:
        service = self._service
        if service is None or not service.is_ready():
            self._stack.setCurrentIndex(0)
            return

        try:
            info = service.get_model_info()
            clickbait = service.get_top_clickbait_features(limit=self._top_n)
            normal = service.get_top_normal_features(limit=self._top_n)
        except (MLModelNotFoundError, ModelInsightsError):
            self._stack.setCurrentIndex(0)
            return

        if info is None:
            self._stack.setCurrentIndex(0)
            return

        self._apply_info(info)
        self._fill_features(self._clickbait_list, clickbait, kind="clickbait")
        self._fill_features(self._normal_list, normal, kind="normal")
        self._stack.setCurrentIndex(1)

    def _apply_info(self, info: ModelInfo) -> None:
        m = info.metrics
        self._algo.setText("TF-IDF + Logistic Regression")
        self._version.setText(f"Version v{info.version}")
        self._trained.setText(f"Trained {_format_trained_at(info)}")
        self._samples.setText(
            f"{m.train_samples} training samples · {m.test_samples} test samples"
        )
        self._class_counts.setText(
            f"Clickbait samples: {m.clickbait_samples} · "
            f"Normal samples: {m.normal_samples}"
        )
        self._metric_acc._value_label.setText(_pct(m.accuracy))  # type: ignore[attr-defined]
        self._metric_prec._value_label.setText(_pct(m.precision))  # type: ignore[attr-defined]
        self._metric_rec._value_label.setText(_pct(m.recall))  # type: ignore[attr-defined]
        self._metric_f1._value_label.setText(_pct(m.f1))  # type: ignore[attr-defined]
        self._last_trained.setText(f"Last trained: {_format_trained_at(info)}")

    def _fill_features(
        self,
        layout: QVBoxLayout,
        features: list[ModelFeature],
        *,
        kind: str,
    ) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not features:
            empty = QLabel("No features yet.")
            empty.setObjectName("metaLabel")
            layout.addWidget(empty)
            return

        max_abs = max(abs(f.coefficient) for f in features) or 1.0
        for feature in features:
            layout.addWidget(
                _FeatureRow(feature, kind=kind, max_abs=max_abs)
            )
