from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from analysis.models import ClickbaitAnalysis
from domain.posts import CatalogPost


class PipelineState(str, Enum):
    IDLE = "idle"
    COLLECTING = "collecting"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PipelineRequest:
    limit: int
    query: str | None = None
    start_from: str | None = None
    exclude_texts: frozenset[str] = field(default_factory=frozenset)
    # When > 0, the worker keeps scanning catalog pages until ``limit`` posts
    # meet this views threshold (or the feed is exhausted).
    min_views: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.limit, int) or isinstance(self.limit, bool):
            raise ValueError("limit must be a positive integer")
        if self.limit <= 0:
            raise ValueError("limit must be > 0")
        if self.query is not None:
            self.query = str(self.query).strip() or None
        if self.start_from is not None:
            self.start_from = str(self.start_from).strip() or None
        if not isinstance(self.exclude_texts, frozenset):
            self.exclude_texts = frozenset(self.exclude_texts)
        self.min_views = max(0, int(self.min_views or 0))


@dataclass
class AnalyzedPost:
    """Post with Rules analysis and optional ML probability (0..1)."""

    post: CatalogPost
    analysis: ClickbaitAnalysis
    ml_score: float | None = None

    @property
    def rules_score(self) -> float:
        return float(self.analysis.score)


@dataclass
class PipelineResult:
    posts: list[AnalyzedPost] = field(default_factory=list)
    collected: int = 0
    analyzed: int = 0
    next_from: str | None = None

    @property
    def has_more(self) -> bool:
        return bool(self.next_from)


@dataclass
class PipelineProgress:
    state: PipelineState
    current: int
    total: int
