from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Protocol

from domain.posts import CatalogPage, CatalogPost, CollectResult, UpsertResult, post_text_key

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
    """Collect global VK catalog posts (optionally into local storage)."""

    # newsfeed.search paginates well with up to 50–100 items per page.
    VK_PAGE_SIZE = 50

    def __init__(
        self,
        *,
        client: CatalogClientProtocol,
        posts: PostRepositoryProtocol | None = None,
        persist_posts: bool = True,
    ) -> None:
        if persist_posts and posts is None:
            raise ValueError("posts repository is required when persist_posts=True")
        self._client = client
        self._posts = posts
        self._persist_posts = bool(persist_posts)
        # Negative session ids for in-memory GUI feed (never collide with SQLite ids).
        self._ephemeral_id = 0

    def collect(
        self,
        *,
        count: int = 100,
        start_from: str | None = None,
        pages: int = 1,
        page_size: int = 100,
        query: str | None = None,
        exclude_texts: frozenset[str] | set[str] | None = None,
        on_progress: CollectProgressCallback | None = None,
    ) -> CollectResult:
        """Fetch up to ``count`` posts with unique text across catalog pages.

        ``count`` sent to VK stays fixed for the whole run — changing it between
        pages breaks ``start_from`` cursors and yields duplicate-only pages.
        Posts with the same normalized text are kept only once (first wins).
        ``exclude_texts`` seeds already-seen normalized texts (e.g. previous UI page).

        When ``persist_posts`` is False, posts stay in memory with ephemeral ids
        and are not written to SQLite.
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
        seen_texts: set[str] = set(exclude_texts or ())
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
            if batch_posts and self._persist_posts and self._posts is not None:
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
                text_key = post_text_key(post.text)
                if text_key:
                    if text_key in seen_texts:
                        continue
                    seen_texts.add(text_key)

                if self._persist_posts and self._posts is not None:
                    loaded = self._posts.get(post.source, post.owner_id, post.post_id)
                    if loaded is None:
                        continue
                    fetched_posts.append(loaded)
                else:
                    self._ephemeral_id -= 1
                    fetched_posts.append(replace(post, id=self._ephemeral_id))
                new_in_page += 1

            if on_progress is not None:
                on_progress(len(fetched_posts), target)

            if not batch_posts:
                last_next = None
                break
            if len(fetched_posts) >= target:
                # Keep last_next so the UI can request the following page.
                break
            if new_in_page == 0:
                stagnant_pages += 1
                # Be patient: newsfeed often repeats before the cursor moves on.
                if stagnant_pages >= 5:
                    break
            else:
                stagnant_pages = 0
            if not page.next_from:
                last_next = None
                break
            if page.next_from == cursor:
                last_next = None
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
        if self._posts is None:
            return []
        return self._posts.get_latest(limit=limit)
