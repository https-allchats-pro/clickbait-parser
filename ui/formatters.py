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
    "continuation_bait": "Continuation bait",
    "curiosity_bait": "Curiosity bait",
    "cta": "Call to action",
    "external_link": "External link",
    "cta_near_link": "CTA near link",
    "short_text_with_link": "Short text + link",
    "ellipsis": "Ellipsis",
    "excessive_punctuation": "Excessive punctuation",
    "caps": "Excessive caps",
    "emoji": "Emoji",
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


def human_state(state: PipelineState) -> str:
    return STATE_LABELS.get(state, state.value)
