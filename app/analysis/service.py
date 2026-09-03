from __future__ import annotations

from typing import Protocol

from analysis.analyzer import PostAnalyzer
from analysis.models import AnalysisBatchResult, ClickbaitAnalysis
from domain.posts import CatalogPost


class PostReader(Protocol):
    def get_by_id(self, post_id: int) -> CatalogPost | None: ...

    def get_latest(self, limit: int = 100) -> list[CatalogPost]: ...


class AnalysisWriter(Protocol):
    def save(self, analysis: ClickbaitAnalysis) -> None: ...

    def save_many(self, analyses: list[ClickbaitAnalysis]) -> None: ...

    def get_by_post_id(self, post_id: int) -> ClickbaitAnalysis | None: ...

    def get_latest(self, limit: int = 100) -> list[ClickbaitAnalysis]: ...

    def get_clickbait(self, limit: int = 100) -> list[ClickbaitAnalysis]: ...


class AnalysisService:
    """Orchestrates PostRepository → ClickbaitAnalyzer → AnalysisRepository."""

    def __init__(
        self,
        *,
        posts: PostReader,
        analyses: AnalysisWriter,
        analyzer: PostAnalyzer,
    ) -> None:
        self._posts = posts
        self._analyses = analyses
        self._analyzer = analyzer

    def analyze_post(self, post_id: int) -> ClickbaitAnalysis:
        post = self._posts.get_by_id(post_id)
        if post is None:
            raise ValueError(f"post {post_id} not found")
        analysis = self._analyzer.analyze(post)
        self._analyses.save(analysis)
        return analysis

    def analyze_posts(self, limit: int = 100) -> AnalysisBatchResult:
        posts = self._posts.get_latest(limit=limit)
        result = AnalysisBatchResult()
        batch: list[ClickbaitAnalysis] = []
        for post in posts:
            if post.id is None:
                result.skipped += 1
                continue
            analysis = self._analyzer.analyze(post)
            batch.append(analysis)
            result.analyzed += 1
            if analysis.is_clickbait:
                result.clickbait += 1
            else:
                result.normal += 1
        self._analyses.save_many(batch)
        return result

    def list_latest(self, limit: int = 20) -> list[tuple[CatalogPost, ClickbaitAnalysis]]:
        analyses = self._analyses.get_latest(limit=limit)
        return self._join_posts(analyses)

    def list_clickbait(self, limit: int = 20) -> list[tuple[CatalogPost, ClickbaitAnalysis]]:
        analyses = self._analyses.get_clickbait(limit=limit)
        return self._join_posts(analyses)

    def _join_posts(
        self,
        analyses: list[ClickbaitAnalysis],
    ) -> list[tuple[CatalogPost, ClickbaitAnalysis]]:
        joined: list[tuple[CatalogPost, ClickbaitAnalysis]] = []
        for analysis in analyses:
            post = self._posts.get_by_id(analysis.post_id)
            if post is None:
                continue
            joined.append((post, analysis))
        return joined
