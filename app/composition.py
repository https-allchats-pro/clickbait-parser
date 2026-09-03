from __future__ import annotations

from analysis.analyzer import RuleBasedClickbaitAnalyzer
from app.catalog.service import CatalogService
from app.pipeline.service import ClickbaitPipeline, ProgressCallback
from infrastructure.db.database import connect, init_schema
from infrastructure.db.repositories.analysis_repository import AnalysisRepository
from infrastructure.db.repositories.post_repository import PostRepository
from infrastructure.vk.catalog_client import VKCatalogClient


def create_clickbait_pipeline(
    *,
    access_token: str,
    threshold: float = 0.5,
    page_size: int = 100,
    on_progress: ProgressCallback | None = None,
) -> ClickbaitPipeline:
    """Wire catalog + analyzer + persistence into a pipeline.

    Call this on the thread that will run the pipeline: SQLite connections are
    bound to the creating thread.
    """
    conn = connect()
    init_schema(conn)
    return ClickbaitPipeline(
        catalog_service=CatalogService(
            client=VKCatalogClient(access_token=access_token),
            posts=PostRepository(conn),
        ),
        analyzer=RuleBasedClickbaitAnalyzer(threshold=threshold),
        analysis_repository=AnalysisRepository(conn),
        on_progress=on_progress,
        page_size=page_size,
    )
