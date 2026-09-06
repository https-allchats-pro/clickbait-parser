from __future__ import annotations

import random
import time
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
from domain.scoring import ScoringConfig, ScoringMode, compute_post_scoring


class CatalogCollector(Protocol):
    def collect(
        self,
        *,
        count: int = 100,
        start_from: str | None = None,
        pages: int = 1,
        page_size: int = 100,
        query: str | None = None,
        exclude_texts: frozenset[str] | set[str] | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        on_progress=None,
    ) -> CollectResult: ...


class AnalysisPersister(Protocol):
    def save_many(self, analyses: list[ClickbaitAnalysis]) -> None: ...


class MlScorer(Protocol):
    def is_ready(self) -> bool: ...

    def predict_proba_clickbait(self, text: str) -> float: ...


ProgressCallback = Callable[[PipelineProgress], None]

# newsfeed.search page size used by CatalogService.
_VK_CATALOG_PAGE_HINT = 50
# Backoff between min-views catalog scans (seconds).
_MIN_VIEWS_DELAY_START = 0.25
_MIN_VIEWS_DELAY_MAX = 2.5


class ClickbaitPipeline:
    """Orchestrates collect → analyze. No VK HTTP / SQLite / clickbait rules inside."""

    def __init__(
        self,
        *,
        catalog_service: CatalogCollector,
        analyzer: PostAnalyzer,
        analysis_repository: AnalysisPersister | None = None,
        ml_scorer: MlScorer | None = None,
        on_progress: ProgressCallback | None = None,
        page_size: int = 100,
    ) -> None:
        self._catalog = catalog_service
        self._analyzer = analyzer
        self._analyses = analysis_repository
        self._ml = ml_scorer
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
            if request.needs_filtered_fill:
                return self._run_until_filters(request, query=query)
            return self._run_once(request, query=query)
        except Exception:
            self._state = PipelineState.FAILED
            self._emit(PipelineProgress(PipelineState.FAILED, 0, request.limit))
            raise
        finally:
            self._on_progress = previous_callback

    def _run_once(
        self,
        request: PipelineRequest,
        *,
        query: str | None,
    ) -> PipelineResult:
        self._set_state(PipelineState.COLLECTING, current=0, total=request.limit)
        pages = self._pages_for_limit(request.limit)

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
            start_from=request.start_from,
            pages=pages,
            page_size=self._page_size,
            query=query,
            exclude_texts=request.exclude_texts,
            start_time=request.start_time,
            end_time=request.end_time,
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
        analyzed_posts = self._analyze_posts(posts, target_total=len(posts))
        return self._complete(
            analyzed_posts,
            collected=len(posts),
            next_from=collect_result.next_from,
        )

    def _run_until_filters(
        self,
        request: PipelineRequest,
        *,
        query: str | None,
    ) -> PipelineResult:
        """Keep collecting until ``limit`` posts match min_views / score_label.

        No batch cap: scans until the quota is filled or the VK cursor is gone.
        Empty / low-yield rounds use an increasing delay so rate limits and
        stagnant cursors can recover.
        """
        matched: list[AnalyzedPost] = []
        scanned = 0
        cursor = request.start_from
        next_from = cursor
        # Keep batches near one UI page. A huge page_size (100+) with a large
        # pages budget burns VK's ~1000-result window and returns next_from=None
        # — pagination then collapses to a single page (esp. week/month windows).
        batch_size = max(request.limit, _VK_CATALOG_PAGE_HINT)
        pages_budget = min(12, self._pages_for_limit(batch_size))
        empty_rounds = 0
        batch_index = 0
        seen_ids: set[tuple[str, int, int]] = set()

        self._set_state(PipelineState.COLLECTING, current=0, total=request.limit)

        while len(matched) < request.limit:
            if batch_index > 0:
                time.sleep(self._filter_fill_delay(batch_index, empty_rounds=empty_rounds))
            batch_index += 1

            def _collect_progress(current: int, total: int) -> None:
                self._emit(
                    PipelineProgress(
                        state=PipelineState.COLLECTING,
                        current=len(matched),
                        total=request.limit,
                    )
                )
                _ = (current, total)

            collect_result = self._catalog.collect(
                count=batch_size,
                start_from=cursor,
                pages=pages_budget,
                page_size=self._page_size,
                query=query,
                start_time=request.start_time,
                end_time=request.end_time,
                on_progress=_collect_progress,
            )
            batch = list(collect_result.posts)
            next_from = collect_result.next_from

            if not batch:
                empty_rounds += 1
                if not next_from or next_from == cursor:
                    break
                cursor = next_from
                continue

            before_matched = len(matched)
            scanned += len(batch)
            analyzed_batch = self._analyze_posts(
                batch,
                target_total=request.limit,
                matched_so_far=len(matched),
            )
            for item in analyzed_batch:
                post = item.post
                key = (post.source, int(post.owner_id), int(post.post_id))
                if key in seen_ids:
                    continue
                seen_ids.add(key)
                if not self._matches_request_filters(item, request):
                    continue
                matched.append(item)
                if len(matched) >= request.limit:
                    break

            if len(matched) == before_matched:
                empty_rounds += 1
            else:
                empty_rounds = 0

            if len(matched) >= request.limit:
                break
            if not next_from or next_from == cursor:
                break
            cursor = next_from

            self._emit(
                PipelineProgress(
                    state=PipelineState.COLLECTING,
                    current=len(matched),
                    total=request.limit,
                )
            )

        return self._complete(
            matched[: request.limit],
            collected=scanned,
            next_from=next_from,
        )

    # Keep old name as alias so existing tests / patches keep working.
    _run_until_min_views = _run_until_filters

    @staticmethod
    def _matches_request_filters(item: AnalyzedPost, request: PipelineRequest) -> bool:
        if request.min_views > 0 and int(item.post.views or 0) < request.min_views:
            return False
        if request.score_label is None:
            return True
        try:
            mode = ScoringMode(request.scoring_mode)
        except ValueError:
            mode = ScoringMode.RULES
        scoring = compute_post_scoring(
            rules_score=item.rules_score,
            ml_score=item.ml_score,
            mode=mode,
            config=ScoringConfig(
                rules_weight=request.scoring_rules_weight,
                ml_weight=request.scoring_ml_weight,
                threshold=request.scoring_threshold,
            ),
        )
        if request.score_label == "clickbait":
            return bool(scoring.is_clickbait)
        if request.score_label == "normal":
            return not bool(scoring.is_clickbait)
        return True

    @staticmethod
    def _filter_fill_delay(batch_index: int, *, empty_rounds: int) -> float:
        """Backoff between filtered catalog scans; grows after empty rounds."""
        base = _MIN_VIEWS_DELAY_START * (1.0 + 0.12 * max(0, batch_index - 1))
        empty_boost = 0.35 * max(0, empty_rounds)
        delay = min(_MIN_VIEWS_DELAY_MAX, base + empty_boost)
        return delay + random.uniform(0.0, 0.12)

    # Backwards-compatible name for tests that patch the delay helper.
    _min_views_delay = _filter_fill_delay

    def _analyze_posts(
        self,
        posts: list,
        *,
        target_total: int,
        matched_so_far: int = 0,
    ) -> list[AnalyzedPost]:
        self._set_state(
            PipelineState.ANALYZING,
            current=matched_so_far,
            total=max(target_total, 1),
        )
        analyzed_posts: list[AnalyzedPost] = []
        analyses: list[ClickbaitAnalysis] = []
        ml_ready = self._ml is not None and self._ml.is_ready()
        for index, post in enumerate(posts, start=1):
            analysis = self._analyzer.analyze(post)
            analyses.append(analysis)
            ml_score: float | None = None
            if ml_ready and self._ml is not None:
                try:
                    ml_score = float(self._ml.predict_proba_clickbait(post.text or ""))
                    ml_score = min(max(ml_score, 0.0), 1.0)
                except Exception:
                    ml_score = None
            analyzed_posts.append(
                AnalyzedPost(post=post, analysis=analysis, ml_score=ml_score)
            )
            self._emit(
                PipelineProgress(
                    PipelineState.ANALYZING,
                    matched_so_far + index,
                    max(target_total, matched_so_far + len(posts)),
                )
            )

        if self._analyses is not None and analyses:
            self._analyses.save_many(analyses)
        return analyzed_posts

    def _complete(
        self,
        analyzed_posts: list[AnalyzedPost],
        *,
        collected: int,
        next_from: str | None,
        query_cursors: dict[str, str | None] | None = None,
    ) -> PipelineResult:
        self._set_state(
            PipelineState.COMPLETED,
            current=len(analyzed_posts),
            total=len(analyzed_posts),
        )
        return PipelineResult(
            posts=analyzed_posts,
            collected=collected,
            analyzed=len(analyzed_posts),
            next_from=next_from,
            query_cursors=dict(query_cursors or {}),
        )

    def _pages_for_limit(self, limit: int) -> int:
        # Extra page budget: VK pages often overlap; collect() also stops on stagnant pages.
        # Deep pagination with a large exclude set needs many more VK pages per UI page.
        return max(
            1,
            limit * 3,
            (limit + self._page_size - 1) // self._page_size,
            (limit + _VK_CATALOG_PAGE_HINT - 1) // _VK_CATALOG_PAGE_HINT,
            30,
        )

    def _set_state(self, state: PipelineState, *, current: int, total: int) -> None:
        self._state = state
        self._emit(PipelineProgress(state=state, current=current, total=total))

    def _emit(self, progress: PipelineProgress) -> None:
        if self._on_progress is not None:
            self._on_progress(progress)
