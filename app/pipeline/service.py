from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from analysis.analyzer import PostAnalyzer
from analysis.models import ClickbaitAnalysis
from domain.pipeline import (
    AnalyzedPost,
    PipelineProgress,
    PipelineRequest,
    PipelineResult,
    PipelineState,
)
from domain.posts import CollectResult


class CatalogCollector(Protocol):
    def collect(
        self,
        *,
        count: int = 100,
        start_from: str | None = None,
        pages: int = 1,
        page_size: int = 100,
        query: str | None = None,
        on_progress=None,
    ) -> CollectResult: ...


class AnalysisPersister(Protocol):
    def save_many(self, analyses: list[ClickbaitAnalysis]) -> None: ...


ProgressCallback = Callable[[PipelineProgress], None]

# newsfeed.search page size used by CatalogService.
_VK_CATALOG_PAGE_HINT = 50


class ClickbaitPipeline:
    """Orchestrates collect → analyze. No VK HTTP / SQLite / clickbait rules inside."""

    def __init__(
        self,
        *,
        catalog_service: CatalogCollector,
        analyzer: PostAnalyzer,
        analysis_repository: AnalysisPersister | None = None,
        on_progress: ProgressCallback | None = None,
        page_size: int = 100,
    ) -> None:
        self._catalog = catalog_service
        self._analyzer = analyzer
        self._analyses = analysis_repository
        self._on_progress = on_progress
        self._page_size = max(1, int(page_size))
        self._state = PipelineState.IDLE

    @property
    def state(self) -> PipelineState:
        return self._state

    def run(
        self,
        request: PipelineRequest,
        *,
        on_progress: ProgressCallback | None = None,
    ) -> PipelineResult:
        # Re-validate in case request was constructed without __post_init__ path.
        if request.limit <= 0:
            raise ValueError("limit must be > 0")
        query = request.query
        if query is not None:
            query = query.strip() or None

        previous_callback = self._on_progress
        if on_progress is not None:
            self._on_progress = on_progress

        try:
            self._set_state(PipelineState.COLLECTING, current=0, total=request.limit)
            # Extra page budget: VK pages often overlap; collect() also stops on stagnant pages.
            pages = max(
                1,
                request.limit,
                (request.limit + self._page_size - 1) // self._page_size,
                (request.limit + _VK_CATALOG_PAGE_HINT - 1) // _VK_CATALOG_PAGE_HINT,
            )

            def _collect_progress(current: int, total: int) -> None:
                self._emit(
                    PipelineProgress(
                        state=PipelineState.COLLECTING,
                        current=current,
                        total=total,
                    )
                )

            collect_result = self._catalog.collect(
                count=request.limit,
                pages=pages,
                page_size=self._page_size,
                query=query,
                on_progress=_collect_progress,
            )
            posts = list(collect_result.posts)[: request.limit]
            self._emit(
                PipelineProgress(
                    state=PipelineState.COLLECTING,
                    current=len(posts),
                    total=request.limit,
                )
            )

            self._set_state(PipelineState.ANALYZING, current=0, total=len(posts))
            analyzed_posts: list[AnalyzedPost] = []
            analyses: list[ClickbaitAnalysis] = []
            for index, post in enumerate(posts, start=1):
                analysis = self._analyzer.analyze(post)
                analyses.append(analysis)
                analyzed_posts.append(AnalyzedPost(post=post, analysis=analysis))
                self._emit(PipelineProgress(PipelineState.ANALYZING, index, len(posts)))

            if self._analyses is not None and analyses:
                self._analyses.save_many(analyses)

            self._set_state(
                PipelineState.COMPLETED,
                current=len(analyzed_posts),
                total=len(analyzed_posts),
            )
            return PipelineResult(
                posts=analyzed_posts,
                collected=len(posts),
                analyzed=len(analyzed_posts),
            )
        except Exception:
            self._state = PipelineState.FAILED
            self._emit(PipelineProgress(PipelineState.FAILED, 0, request.limit))
            raise
        finally:
            self._on_progress = previous_callback

    def _set_state(self, state: PipelineState, *, current: int, total: int) -> None:
        self._state = state
        self._emit(PipelineProgress(state=state, current=current, total=total))

    def _emit(self, progress: PipelineProgress) -> None:
        if self._on_progress is not None:
            self._on_progress(progress)
