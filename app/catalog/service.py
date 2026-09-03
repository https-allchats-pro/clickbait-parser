from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from domain.posts import CatalogPage, CatalogPost, CollectResult, UpsertResult

CollectProgressCallback = Callable[[int, int], None]


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

    # newsfeed.search paginates well with up to 50–100 items per page.
    VK_PAGE_SIZE = 50

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
        on_progress: CollectProgressCallback | None = None,
    ) -> CollectResult:
        """Fetch up to ``count`` unique posts across catalog pages.

        ``count`` sent to VK stays fixed for the whole run — changing it between
        pages breaks ``start_from`` cursors and yields duplicate-only pages.
        """
        target = max(0, int(count))
        effective_page_size = self.VK_PAGE_SIZE
        # Allow extra pages: feeds often repeat items across cursors.
        max_pages = max(
            1,
            int(pages),
            (target + effective_page_size - 1) // effective_page_size,
            target,  # worst case: 1 new unique post per page
        )
        if query is not None:
            query = str(query).strip() or None

        cursor = start_from
        total_upsert = UpsertResult()
        fetched_posts: list[CatalogPost] = []
        pages_done = 0
        last_next: str | None = None
        seen: set[tuple[str, int, int]] = set()
        stagnant_pages = 0

        while len(fetched_posts) < target and pages_done < max_pages:
            page = self._client.get_search_top(
                count=effective_page_size,
                start_from=cursor,
                query=query,
            )
            pages_done += 1
            last_next = page.next_from

            batch_posts = page.posts
            new_in_page = 0
            if batch_posts:
                part = self._posts.upsert_many(batch_posts)
                total_upsert = UpsertResult(
                    inserted=total_upsert.inserted + part.inserted,
                    updated=total_upsert.updated + part.updated,
                    unchanged=total_upsert.unchanged + part.unchanged,
                )
                for post in batch_posts:
                    if len(fetched_posts) >= target:
                        break
                    key = (post.source, post.owner_id, post.post_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    loaded = self._posts.get(post.source, post.owner_id, post.post_id)
                    if loaded is not None:
                        fetched_posts.append(loaded)
                        new_in_page += 1

            if on_progress is not None:
                on_progress(len(fetched_posts), target)

            if not batch_posts:
                break
            if new_in_page == 0:
                stagnant_pages += 1
                if stagnant_pages >= 2:
                    break
            else:
                stagnant_pages = 0
            if not page.next_from:
                break
            if page.next_from == cursor:
                break
            cursor = page.next_from

        return CollectResult(
            fetched=len(fetched_posts),
            upsert=total_upsert,
            next_from=last_next,
            pages=pages_done,
            posts=fetched_posts[:target],
        )

    def list_latest(self, *, limit: int = 20) -> list[CatalogPost]:
        return self._posts.get_latest(limit=limit)
