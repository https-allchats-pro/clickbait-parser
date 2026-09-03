from __future__ import annotations

from typing import Protocol

from domain.posts import CatalogPage, CatalogPost, CollectResult, UpsertResult


class CatalogClientProtocol(Protocol):
    def get_search_top(
        self,
        *,
        count: int = 100,
        start_from: str | None = None,
        query: str | None = None,
    ) -> CatalogPage: ...


class PostRepositoryProtocol(Protocol):
    def upsert_many(self, posts: list[CatalogPost]) -> UpsertResult: ...

    def get_latest(self, limit: int = 100) -> list[CatalogPost]: ...

    def get(
        self,
        source: str,
        owner_id: int,
        post_id: int,
    ) -> CatalogPost | None: ...


class CatalogService:
    """Collect global VK catalog posts into local storage."""

    def __init__(
        self,
        *,
        client: CatalogClientProtocol,
        posts: PostRepositoryProtocol,
    ) -> None:
        self._client = client
        self._posts = posts

    def collect(
        self,
        *,
        count: int = 100,
        start_from: str | None = None,
        pages: int = 1,
        page_size: int = 100,
        query: str | None = None,
    ) -> CollectResult:
        """Fetch up to ``count`` posts across at most ``pages`` catalog pages."""
        remaining = max(0, int(count))
        max_pages = max(1, int(pages))
        cursor = start_from
        total_upsert = UpsertResult()
        fetched = 0
        pages_done = 0
        last_next: str | None = None

        while remaining > 0 and pages_done < max_pages:
            batch = min(remaining, max(1, int(page_size)))
            page = self._client.get_search_top(
                count=batch,
                start_from=cursor,
                query=query,
            )
            pages_done += 1
            last_next = page.next_from

            batch_posts = page.posts[:remaining]
            fetched += len(batch_posts)
            if batch_posts:
                part = self._posts.upsert_many(batch_posts)
                total_upsert = UpsertResult(
                    inserted=total_upsert.inserted + part.inserted,
                    updated=total_upsert.updated + part.updated,
                    unchanged=total_upsert.unchanged + part.unchanged,
                )

            remaining = count - fetched
            if not page.next_from or not batch_posts:
                break
            if page.next_from == cursor:
                break
            cursor = page.next_from

        return CollectResult(
            fetched=fetched,
            upsert=total_upsert,
            next_from=last_next,
            pages=pages_done,
        )

    def list_latest(self, *, limit: int = 20) -> list[CatalogPost]:
        return self._posts.get_latest(limit=limit)
