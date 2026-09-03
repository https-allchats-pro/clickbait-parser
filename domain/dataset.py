from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DatasetLabel(str, Enum):
    CLICKBAIT = "clickbait"
    NORMAL = "normal"
    BORDERLINE = "borderline"


@dataclass
class PostLabel:
    """Human ground-truth label for a local posts.id (not rule prediction)."""

    post_id: int
    label: DatasetLabel
    created_at: int
    updated_at: int
    note: str | None = None
    id: int | None = None


@dataclass
class DatasetStats:
    total_labeled: int
    unlabeled: int
    by_label: dict[DatasetLabel, int]
    rule_clickbait: int
    rule_normal: int
    disagreement_human_clickbait_rule_normal: int
    disagreement_human_normal_rule_clickbait: int


@dataclass
class DatasetValidation:
    total_labeled: int
    by_label: dict[DatasetLabel, int]
    warnings: list[str]


# Soft quality thresholds for ``dataset validate`` (warnings only).
MIN_CLICKBAIT_FOR_ML = 200
MIN_NORMAL_FOR_ML = 200
MAX_IMBALANCE_RATIO = 3.0  # majority / minority among clickbait+normal
