from __future__ import annotations

"""Central themes for the PyQt6 UI (presentation only)."""

from typing import Literal

from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication, QWidget

# Spacing scale
SP_4 = 4
SP_8 = 8
SP_12 = 12
SP_16 = 16
SP_24 = 24

ThemeName = Literal["dark", "light"]

_SETTINGS_ORG = "clickbait-parser"
_SETTINGS_APP = "ui"
_SETTINGS_KEY = "theme"
_DEFAULT_THEME: ThemeName = "dark"

DARK_COLORS: dict[str, str] = {
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
    "error_bg": "#3a1f1f",
    "error_border": "#5c2b2b",
    "button_hover": "#48484a",
    "button_pressed": "#3a3a3c",
    "button_disabled_bg": "#2c2c2e",
    "button_disabled_text": "#636366",
    "primary_disabled_bg": "#3a3a3c",
    "primary_disabled_text": "#8e8e93",
    "scrollbar": "#48484a",
    "clickbait_soft": "rgba(255, 69, 58, 0.18)",
    "normal_soft": "rgba(48, 209, 88, 0.18)",
    "borderline_soft": "rgba(152, 152, 157, 0.22)",
    "primary_text": "#ffffff",
}

LIGHT_COLORS: dict[str, str] = {
    "bg": "#f5f5f7",
    "bg_elevated": "#ffffff",
    "bg_input": "#e8e8ed",
    "border": "#d2d2d7",
    "text": "#1d1d1f",
    "text_secondary": "#6e6e73",
    "accent": "#0071e3",
    "accent_hover": "#0077ed",
    "accent_pressed": "#0058b0",
    "danger": "#d70015",
    "clickbait": "#d70015",
    "normal": "#248a3d",
    "chip_bg": "#e5e5ea",
    "error_bg": "#fff2f2",
    "error_border": "#ffc9c9",
    "button_hover": "#dcdce0",
    "button_pressed": "#d2d2d7",
    "button_disabled_bg": "#f0f0f2",
    "button_disabled_text": "#aeaeb2",
    "primary_disabled_bg": "#d2d2d7",
    "primary_disabled_text": "#8e8e93",
    "scrollbar": "#c7c7cc",
    "clickbait_soft": "rgba(215, 0, 21, 0.12)",
    "normal_soft": "rgba(36, 138, 61, 0.12)",
    "borderline_soft": "rgba(110, 110, 115, 0.14)",
    "primary_text": "#ffffff",
}

THEMES: dict[ThemeName, dict[str, str]] = {
    "dark": DARK_COLORS,
    "light": LIGHT_COLORS,
}

# Mutable module state — updated by apply_theme.
COLORS: dict[str, str] = dict(DARK_COLORS)
CURRENT_THEME: ThemeName = _DEFAULT_THEME
APP_STYLESHEET = ""


def _normalize_theme(name: str | None) -> ThemeName:
    if name == "light":
        return "light"
    return "dark"


def load_saved_theme() -> ThemeName:
    settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
    return _normalize_theme(settings.value(_SETTINGS_KEY, _DEFAULT_THEME))


def save_theme(name: ThemeName) -> None:
    settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
    settings.setValue(_SETTINGS_KEY, name)


def build_stylesheet(colors: dict[str, str]) -> str:
    return f"""
QWidget {{
    background-color: {colors["bg"]};
    color: {colors["text"]};
    font-size: 13px;
}}

QMainWindow, QDialog {{
    background-color: {colors["bg"]};
}}

QLabel#sectionLabel {{
    color: {colors["text_secondary"]};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.3px;
}}

QLabel#secondaryLabel {{
    color: {colors["text_secondary"]};
    font-size: 12px;
}}

QLabel#progressTitle {{
    font-size: 13px;
    font-weight: 500;
}}

QLabel#progressCount {{
    color: {colors["text_secondary"]};
    font-size: 12px;
}}

QLabel#statusFooter {{
    color: {colors["text_secondary"]};
    font-size: 12px;
}}

QLabel#statValue {{
    font-size: 22px;
    font-weight: 600;
}}

QLabel#statCaption {{
    color: {colors["text_secondary"]};
    font-size: 11px;
}}

QLabel#emptyTitle {{
    font-size: 16px;
    font-weight: 600;
}}

QLabel#emptyHint {{
    color: {colors["text_secondary"]};
    font-size: 13px;
}}

QLabel#errorTitle {{
    color: {colors["danger"]};
    font-size: 14px;
    font-weight: 600;
}}

QLabel#errorDetail {{
    color: {colors["text_secondary"]};
    font-size: 12px;
}}

QFrame#panel, QFrame#statCard, QFrame#postCard {{
    background-color: {colors["bg_elevated"]};
    border: 1px solid {colors["border"]};
    border-radius: 12px;
}}

QFrame#errorPanel {{
    background-color: {colors["error_bg"]};
    border: 1px solid {colors["error_border"]};
    border-radius: 12px;
}}

QFrame#cardDivider {{
    background-color: {colors["border"]};
    border: none;
    max-height: 1px;
}}

QLineEdit, QSpinBox, QComboBox, QListWidget {{
    background-color: {colors["bg_input"]};
    border: 1px solid {colors["border"]};
    border-radius: 8px;
    padding: 8px 10px;
    selection-background-color: {colors["accent"]};
}}

QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 1px solid {colors["accent"]};
}}

QComboBox::drop-down {{
    border: none;
    width: 24px;
}}

QComboBox QAbstractItemView {{
    background-color: {colors["bg_elevated"]};
    border: 1px solid {colors["border"]};
    selection-background-color: {colors["accent"]};
}}

QSpinBox::up-button, QSpinBox::down-button {{
    width: 18px;
}}

QPushButton {{
    background-color: {colors["bg_input"]};
    border: 1px solid {colors["border"]};
    border-radius: 8px;
    padding: 8px 14px;
    color: {colors["text"]};
}}

QPushButton:hover {{
    background-color: {colors["button_hover"]};
}}

QPushButton:pressed {{
    background-color: {colors["button_pressed"]};
}}

QPushButton:disabled {{
    color: {colors["button_disabled_text"]};
    background-color: {colors["button_disabled_bg"]};
}}

QPushButton#primaryButton {{
    background-color: {colors["accent"]};
    border: none;
    color: {colors["primary_text"]};
    font-weight: 600;
    padding: 10px 18px;
    min-width: 120px;
}}

QPushButton#primaryButton:hover {{
    background-color: {colors["accent_hover"]};
}}

QPushButton#primaryButton:pressed {{
    background-color: {colors["accent_pressed"]};
}}

QPushButton#primaryButton:disabled {{
    background-color: {colors["primary_disabled_bg"]};
    color: {colors["primary_disabled_text"]};
}}

QPushButton#filterButton {{
    background-color: transparent;
    border: none;
    border-radius: 8px;
    padding: 6px 12px;
    color: {colors["text_secondary"]};
}}

QPushButton#filterButton:hover {{
    background-color: {colors["bg_input"]};
    color: {colors["text"]};
}}

QPushButton#filterButton:checked {{
    background-color: {colors["bg_input"]};
    color: {colors["text"]};
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
    background-color: {colors["bg_input"]};
}}

QPushButton#labelGood, QPushButton#labelBad, QPushButton#labelBorderline {{
    background-color: {colors["bg_input"]};
    border: 1px solid {colors["border"]};
    border-radius: 8px;
    padding: 6px 12px;
    color: {colors["text_secondary"]};
    font-weight: 500;
}}

QPushButton#labelGood:hover {{
    color: {colors["clickbait"]};
    border-color: {colors["clickbait"]};
}}

QPushButton#labelGood:checked {{
    background-color: {colors["clickbait_soft"]};
    color: {colors["clickbait"]};
    border-color: {colors["clickbait"]};
    font-weight: 700;
}}

QPushButton#labelBad:hover {{
    color: {colors["normal"]};
    border-color: {colors["normal"]};
}}

QPushButton#labelBad:checked {{
    background-color: {colors["normal_soft"]};
    color: {colors["normal"]};
    border-color: {colors["normal"]};
    font-weight: 700;
}}

QPushButton#labelBorderline:hover {{
    color: {colors["text"]};
    border-color: {colors["text_secondary"]};
}}

QPushButton#labelBorderline:checked {{
    background-color: {colors["borderline_soft"]};
    color: {colors["text"]};
    border-color: {colors["text_secondary"]};
    font-weight: 700;
}}

QPushButton#linkButton {{
    background-color: transparent;
    border: none;
    color: {colors["accent"]};
    padding: 0;
    text-align: left;
}}

QPushButton#linkButton:hover {{
    color: {colors["accent_hover"]};
}}

QProgressBar {{
    background-color: {colors["bg_input"]};
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
    color: transparent;
}}

QProgressBar::chunk {{
    background-color: {colors["accent"]};
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
    background: {colors["scrollbar"]};
    border-radius: 5px;
    min-height: 24px;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QSplitter#mainSplitter::handle:vertical {{
    background: {colors["border"]};
    margin: 4px 80px;
    border-radius: 3px;
}}

QSplitter#mainSplitter::handle:vertical:hover {{
    background: {colors["accent"]};
}}

QLabel#predictionClickbait {{
    background-color: {colors["clickbait_soft"]};
    color: {colors["clickbait"]};
    border-radius: 6px;
    padding: 4px 10px;
    font-weight: 700;
    font-size: 12px;
}}

QLabel#predictionNormal {{
    background-color: {colors["normal_soft"]};
    color: {colors["normal"]};
    border-radius: 6px;
    padding: 4px 10px;
    font-weight: 700;
    font-size: 12px;
}}

QLabel#scoreBadge {{
    color: {colors["text"]};
    font-size: 18px;
    font-weight: 700;
}}

QLabel#postText {{
    font-size: 14px;
    line-height: 1.45;
}}

QLabel#metaLabel {{
    color: {colors["text_secondary"]};
    font-size: 12px;
}}

QLabel#reasonChip {{
    background-color: {colors["chip_bg"]};
    color: {colors["text"]};
    border-radius: 10px;
    padding: 4px 10px;
    font-size: 11px;
}}

QLabel#reasonsTitle {{
    color: {colors["text_secondary"]};
    font-size: 11px;
    font-weight: 600;
}}

QTabWidget::pane {{
    border: none;
    background: transparent;
    top: -1px;
}}

QTabBar::tab {{
    background: transparent;
    color: {colors["text_secondary"]};
    padding: 8px 16px;
    margin-right: 4px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 500;
}}

QTabBar::tab:hover {{
    color: {colors["text"]};
}}

QTabBar::tab:selected {{
    color: {colors["text"]};
    border-bottom: 2px solid {colors["accent"]};
    font-weight: 600;
}}

QLabel#insightsTitle {{
    font-size: 18px;
    font-weight: 600;
}}

QLabel#insightsAlgo {{
    font-size: 15px;
    font-weight: 600;
}}

QLabel#insightsHowTo {{
    color: {colors["text_secondary"]};
    font-size: 12px;
    line-height: 1.4;
}}

QLabel#insightsClickbaitHead {{
    color: {colors["clickbait"]};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.4px;
}}

QLabel#insightsNormalHead {{
    color: {colors["normal"]};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.4px;
}}

QLabel#featureTerm {{
    font-size: 12px;
    color: {colors["text"]};
}}

QLabel#featureCoefClickbait {{
    color: {colors["clickbait"]};
    font-size: 12px;
    font-weight: 600;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}}

QLabel#featureCoefNormal {{
    color: {colors["normal"]};
    font-size: 12px;
    font-weight: 600;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}}

QProgressBar#featureBarClickbait {{
    background-color: {colors["bg_input"]};
    border: none;
    border-radius: 4px;
    max-height: 8px;
}}

QProgressBar#featureBarClickbait::chunk {{
    background-color: {colors["clickbait"]};
    border-radius: 4px;
}}

QProgressBar#featureBarNormal {{
    background-color: {colors["bg_input"]};
    border: none;
    border-radius: 4px;
    max-height: 8px;
}}

QProgressBar#featureBarNormal::chunk {{
    background-color: {colors["normal"]};
    border-radius: 4px;
}}
"""


def apply_theme(
    app: QApplication,
    theme: ThemeName | None = None,
    *,
    persist: bool = True,
) -> ThemeName:
    global COLORS, CURRENT_THEME, APP_STYLESHEET

    name = _normalize_theme(theme if theme is not None else load_saved_theme())
    COLORS = dict(THEMES[name])
    CURRENT_THEME = name
    APP_STYLESHEET = build_stylesheet(COLORS)

    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)
    if persist:
        save_theme(name)
    return name


def get_current_theme() -> ThemeName:
    return CURRENT_THEME


def toggle_theme(app: QApplication) -> ThemeName:
    next_theme: ThemeName = "light" if CURRENT_THEME == "dark" else "dark"
    return apply_theme(app, next_theme)


def set_object_name(widget: QWidget, name: str) -> None:
    widget.setObjectName(name)


# Build default stylesheet so APP_STYLESHEET is never empty for importers.
APP_STYLESHEET = build_stylesheet(COLORS)
