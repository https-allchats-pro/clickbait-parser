from __future__ import annotations

from datetime import datetime

from domain.pipeline import PipelineState

_MONTHS_RU = (
    "янв.",
    "февр.",
    "мар.",
    "апр.",
    "мая",
    "июн.",
    "июл.",
    "авг.",
    "сент.",
    "окт.",
    "нояб.",
    "дек.",
)

REASON_LABELS: dict[str, str] = {
    "continuation_bait": "Продолжение по ссылке",
    "curiosity_bait": "Любопытство / интрига",
    "cta": "Призыв к действию",
    "external_link": "Внешняя ссылка",
    "cta_near_link": "Призыв рядом со ссылкой",
    "short_text_with_link": "Короткий текст + ссылка",
    "ellipsis": "Многоточие",
    "excessive_punctuation": "Лишняя пунктуация",
    "caps": "КРИЧАЩИЙ КАПС",
    "emoji": "Эмодзи",
}

STATE_LABELS: dict[PipelineState, str] = {
    PipelineState.IDLE: "Готово",
    PipelineState.COLLECTING: "Сбор постов",
    PipelineState.ANALYZING: "Анализ постов",
    PipelineState.COMPLETED: "Готово",
    PipelineState.FAILED: "Ошибка",
}


def format_score_percent(score: float) -> str:
    return f"{round(float(score) * 100)}%"


def format_score_or_dash(score: float | None) -> str:
    if score is None:
        return "—"
    return format_score_percent(score)


def format_reason(reason: str) -> str:
    return REASON_LABELS.get(reason, reason.replace("_", " ").strip().title())


def format_post_date(value: datetime | None) -> str:
    if not isinstance(value, datetime):
        return "—"
    local = value.astimezone()
    month = _MONTHS_RU[local.month - 1]
    return f"{local.day} {month} {local.year}, {local.strftime('%H:%M')}"


def format_links_label(count: int) -> str:
    if count <= 0:
        return "Нет ссылок"
    if count == 1:
        return "1 ссылка"
    if 2 <= count <= 4:
        return f"{count} ссылки"
    return f"{count} ссылок"


def format_views_label(count: int) -> str:
    value = max(0, int(count))
    if value == 0:
        return "0 просмотров"
    # Compact thousands: 12.5K
    if value >= 1_000_000:
        text = f"{value / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
    elif value >= 10_000:
        text = f"{value / 1_000:.1f}".rstrip("0").rstrip(".") + "K"
    else:
        text = f"{value:,}".replace(",", " ")
    if value % 10 == 1 and value % 100 != 11:
        unit = "просмотр"
    elif 2 <= value % 10 <= 4 and not (12 <= value % 100 <= 14):
        unit = "просмотра"
    else:
        unit = "просмотров"
    return f"{text} {unit}"


def human_state(state: PipelineState) -> str:
    return STATE_LABELS.get(state, state.value)
