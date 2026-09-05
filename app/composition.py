from __future__ import annotations

from analysis.analyzer import RuleBasedClickbaitAnalyzer
from app.catalog.service import CatalogService
from app.ml.predictor import MLPredictor
from app.ml.storage import ModelStore
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
    model_store: ModelStore | None = None,
    persist: bool = False,
) -> ClickbaitPipeline:
    """Wire catalog + analyzer + ML scorer into a pipeline.

    Call this on the thread that will run the pipeline: SQLite connections are
    bound to the creating thread.

    By default (``persist=False``) the GUI feed stays in memory — posts/analyses
    are written to SQLite only when the user labels them. Set ``persist=True``
    to restore the old collect+analyze DB write path.
    """
    store = model_store or ModelStore()
    if persist:
        conn = connect()
        init_schema(conn)
        catalog = CatalogService(
            client=VKCatalogClient(access_token=access_token),
            posts=PostRepository(conn),
            persist_posts=True,
        )
        analyses: AnalysisRepository | None = AnalysisRepository(conn)
    else:
        catalog = CatalogService(
            client=VKCatalogClient(access_token=access_token),
            posts=None,
            persist_posts=False,
        )
        analyses = None

    return ClickbaitPipeline(
        catalog_service=catalog,
        analyzer=RuleBasedClickbaitAnalyzer(threshold=threshold),
        analysis_repository=analyses,
        ml_scorer=MLPredictor(store),
        on_progress=on_progress,
        page_size=page_size,
    )
