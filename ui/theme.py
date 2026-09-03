from __future__ import annotations

"""Central dark theme for the PyQt6 UI (presentation only)."""

from PyQt6.QtWidgets import QApplication, QWidget

# Spacing scale
SP_4 = 4
SP_8 = 8
SP_12 = 12
SP_16 = 16
SP_24 = 24

COLORS = {
    "bg": "#1c1c1e",
    "bg_elevated": "#2c2c2e",
    "bg_input": "#3a3a3c",
    "border": "#3a3a3c",
    "text": "#f5f5f7",
    "text_secondary": "#98989d",
    "accent": "#0a84ff",
    "accent_hover": "#409cff",
    "accent_pressed": "#0071e3",
    "danger": "#ff453a",
    "clickbait": "#ff453a",
    "normal": "#30d158",
    "chip_bg": "#48484a",
}


APP_STYLESHEET = f"""
QWidget {{
    background-color: {COLORS["bg"]};
    color: {COLORS["text"]};
    font-size: 13px;
}}

QMainWindow, QDialog {{
    background-color: {COLORS["bg"]};
}}

QLabel#sectionLabel {{
    color: {COLORS["text_secondary"]};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.3px;
}}

QLabel#secondaryLabel {{
    color: {COLORS["text_secondary"]};
    font-size: 12px;
}}

QLabel#progressTitle {{
    font-size: 13px;
    font-weight: 500;
}}

QLabel#progressCount {{
    color: {COLORS["text_secondary"]};
    font-size: 12px;
}}

QLabel#statusFooter {{
    color: {COLORS["text_secondary"]};
    font-size: 12px;
}}

QLabel#statValue {{
    font-size: 22px;
    font-weight: 600;
}}

QLabel#statCaption {{
    color: {COLORS["text_secondary"]};
    font-size: 11px;
}}

QLabel#emptyTitle {{
    font-size: 16px;
    font-weight: 600;
}}

QLabel#emptyHint {{
    color: {COLORS["text_secondary"]};
    font-size: 13px;
}}

QLabel#errorTitle {{
    color: {COLORS["danger"]};
    font-size: 14px;
    font-weight: 600;
}}

QLabel#errorDetail {{
    color: {COLORS["text_secondary"]};
    font-size: 12px;
}}

QFrame#panel, QFrame#statCard, QFrame#postCard {{
    background-color: {COLORS["bg_elevated"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 12px;
}}

QFrame#errorPanel {{
    background-color: #3a1f1f;
    border: 1px solid #5c2b2b;
    border-radius: 12px;
}}

QLineEdit, QSpinBox, QListWidget {{
    background-color: {COLORS["bg_input"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 8px;
    padding: 8px 10px;
    selection-background-color: {COLORS["accent"]};
}}

QLineEdit:focus, QSpinBox:focus {{
    border: 1px solid {COLORS["accent"]};
}}

QSpinBox::up-button, QSpinBox::down-button {{
    width: 18px;
}}

QPushButton {{
    background-color: {COLORS["bg_input"]};
    border: 1px solid {COLORS["border"]};
    border-radius: 8px;
    padding: 8px 14px;
    color: {COLORS["text"]};
}}

QPushButton:hover {{
    background-color: #48484a;
}}

QPushButton:pressed {{
    background-color: #3a3a3c;
}}

QPushButton:disabled {{
    color: #636366;
    background-color: #2c2c2e;
}}

QPushButton#primaryButton {{
    background-color: {COLORS["accent"]};
    border: none;
    color: white;
    font-weight: 600;
    padding: 10px 18px;
    min-width: 120px;
}}

QPushButton#primaryButton:hover {{
    background-color: {COLORS["accent_hover"]};
}}

QPushButton#primaryButton:pressed {{
    background-color: {COLORS["accent_pressed"]};
}}

QPushButton#primaryButton:disabled {{
    background-color: #3a3a3c;
    color: #8e8e93;
}}

QPushButton#filterButton {{
    background-color: transparent;
    border: none;
    border-radius: 8px;
    padding: 6px 12px;
    color: {COLORS["text_secondary"]};
}}

QPushButton#filterButton:hover {{
    background-color: {COLORS["bg_input"]};
    color: {COLORS["text"]};
}}

QPushButton#filterButton:checked {{
    background-color: {COLORS["bg_input"]};
    color: {COLORS["text"]};
    font-weight: 600;
}}

QPushButton#iconButton {{
    background-color: transparent;
    border: none;
    border-radius: 6px;
    padding: 6px;
    min-width: 32px;
}}

QPushButton#iconButton:hover {{
    background-color: {COLORS["bg_input"]};
}}

QPushButton#linkButton {{
    background-color: transparent;
    border: none;
    color: {COLORS["accent"]};
    padding: 0;
    text-align: left;
}}

QPushButton#linkButton:hover {{
    color: {COLORS["accent_hover"]};
}}

QProgressBar {{
    background-color: {COLORS["bg_input"]};
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
    color: transparent;
}}

QProgressBar::chunk {{
    background-color: {COLORS["accent"]};
    border-radius: 4px;
}}

QScrollArea {{
    border: none;
    background: transparent;
}}

QScrollArea > QWidget > QWidget {{
    background: transparent;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: #48484a;
    border-radius: 5px;
    min-height: 24px;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QLabel#predictionClickbait {{
    background-color: rgba(255, 69, 58, 0.18);
    color: {COLORS["clickbait"]};
    border-radius: 6px;
    padding: 4px 10px;
    font-weight: 700;
    font-size: 12px;
}}

QLabel#predictionNormal {{
    background-color: rgba(48, 209, 88, 0.18);
    color: {COLORS["normal"]};
    border-radius: 6px;
    padding: 4px 10px;
    font-weight: 700;
    font-size: 12px;
}}

QLabel#scoreBadge {{
    color: {COLORS["text"]};
    font-size: 18px;
    font-weight: 700;
}}

QLabel#postText {{
    font-size: 14px;
    line-height: 1.45;
}}

QLabel#metaLabel {{
    color: {COLORS["text_secondary"]};
    font-size: 12px;
}}

QLabel#reasonChip {{
    background-color: {COLORS["chip_bg"]};
    color: {COLORS["text"]};
    border-radius: 10px;
    padding: 4px 10px;
    font-size: 11px;
}}

QLabel#reasonsTitle {{
    color: {COLORS["text_secondary"]};
    font-size: 11px;
    font-weight: 600;
}}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)


def set_object_name(widget: QWidget, name: str) -> None:
    widget.setObjectName(name)
