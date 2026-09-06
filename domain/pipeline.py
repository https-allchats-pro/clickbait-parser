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
    # When non-empty, the worker runs each query sequentially (``limit`` posts each).
    queries: tuple[str, ...] = ()
    start_from: str | None = None
    # Per-query VK cursors for multi-query load-more.
    # Missing key → start from the beginning; explicit None → that query is exhausted.
    query_cursors: dict[str, str | None] = field(default_factory=dict)
    exclude_texts: frozenset[str] = field(default_factory=frozenset)
    # When > 0, the worker keeps scanning catalog pages until ``limit`` posts
    # meet this views threshold (or the feed is exhausted).
    min_views: int = 0
    # VK newsfeed.search time window (unix seconds). None → API defaults (~last day).
    start_time: int | None = None
    end_time: int | None = None
    # When set to "clickbait" / "normal", the worker keeps scanning until
    # ``limit`` posts match that label under the given scoring settings.
    score_label: str | None = None
    scoring_mode: str = "rules"
    scoring_threshold: float = 0.70
    scoring_rules_weight: float = 0.3
    scoring_ml_weight: float = 0.7
    # GUI pagination: append to the in-memory buffer and open ``target_page``.
    append: bool = False
    target_page: int | None = None

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
        if self.start_time is not None:
            self.start_time = max(0, int(self.start_time))
        if self.end_time is not None:
            self.end_time = max(0, int(self.end_time))
        if (
            self.start_time is not None
            and self.end_time is not None
            and self.start_time > self.end_time
        ):
            self.start_time, self.end_time = self.end_time, self.start_time
        label = str(self.score_label or "").strip().casefold() or None
        if label is not None and label not in {"clickbait", "normal"}:
            raise ValueError("score_label must be 'clickbait', 'normal', or None")
        self.score_label = label
        self.scoring_mode = str(self.scoring_mode or "rules").strip().casefold() or "rules"
        self.scoring_threshold = float(self.scoring_threshold)
        self.scoring_rules_weight = float(self.scoring_rules_weight)
        self.scoring_ml_weight = float(self.scoring_ml_weight)
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in self.queries:
            term = str(raw).strip()
            if not term:
                continue
            key = term.casefold()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(term)
        self.queries = tuple(cleaned)
        if not isinstance(self.query_cursors, dict):
            self.query_cursors = dict(self.query_cursors)

    @property
    def needs_filtered_fill(self) -> bool:
        """True when the worker must scan until ``limit`` matching posts."""
        return self.min_views > 0 or self.score_label is not None


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
    query_cursors: dict[str, str | None] = field(default_factory=dict)

    @property
    def has_more(self) -> bool:
        if self.query_cursors:
            return any(self.query_cursors.values())
        return bool(self.next_from)


@dataclass
class PipelineProgress:
    state: PipelineState
    current: int
    total: int
