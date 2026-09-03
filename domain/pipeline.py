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


@dataclass
class AnalyzedPost:
    post: CatalogPost
    analysis: ClickbaitAnalysis


@dataclass
class PipelineResult:
    posts: list[AnalyzedPost] = field(default_factory=list)
    collected: int = 0
    analyzed: int = 0
    next_from: str | None = None


@dataclass
class PipelineProgress:
    state: PipelineState
    current: int
    total: int
