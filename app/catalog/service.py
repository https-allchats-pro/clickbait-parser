from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
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
        start_time: int | None = None,
        end_time: int | None = None,
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
    # Stop only after many duplicate-only pages while the cursor still moves.
    # Early stop (~5) cuts the feed around 40–60 posts once exclude_texts is large.
    STAGNANT_HARD_CAP = 40
    MAX_PAGES_CAP = 200

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
        start_time: int | None = None,
        end_time: int | None = None,
        on_progress: CollectProgressCallback | None = None,
    ) -> CollectResult:
        """Fetch up to ``count`` posts across catalog pages.

        ``count`` sent to VK stays fixed for the whole run — changing it between
        pages breaks ``start_from`` cursors and yields duplicate-only pages.
        Exact VK posts (source/owner/post_id) are kept only once. Identical text
        from different posts is allowed so deep pagination is not starved.

        ``start_time`` / ``end_time`` are passed to ``newsfeed.search`` (unix).

        When ``persist_posts`` is False, posts stay in memory with ephemeral ids
        and are not written to SQLite.
        """
        target = max(0, int(count))
        effective_page_size = self.VK_PAGE_SIZE
        # Allow extra pages: feeds often repeat items across cursors.
        # Always hard-cap: unbounded scans burn VK's ~1000-result window and
        # leave the UI with next_from=None (pagination stuck on page 1).
        max_pages = min(
            self.MAX_PAGES_CAP,
            max(
                1,
                int(pages),
                (target + effective_page_size - 1) // effective_page_size,
                min(target, 40),  # worst case: 1 new post per page, bounded
                min(self.MAX_PAGES_CAP, target * 3 + 10),
            ),
        )
        if query is not None:
            query = str(query).strip() or None

        cursor = start_from
        total_upsert = UpsertResult()
        fetched_posts: list[CatalogPost] = []
        pages_done = 0
        last_next: str | None = None
        seen: set[tuple[str, int, int]] = set()
        # Optional seed of already-known VK ids (source, owner_id, post_id).
        # ``exclude_texts`` is accepted for API compatibility but ignored: text
        # dedupe starved deep pagination (Clickbait page 3+).
        _ = exclude_texts
        stagnant_pages = 0

        while len(fetched_posts) < target and pages_done < max_pages:
            page = self._client.get_search_top(
                count=effective_page_size,
                start_from=cursor,
                query=query,
                start_time=start_time,
                end_time=end_time,
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
                # Mapper may return [] while VK still provides next_from — do not
                # kill the cursor (that used to freeze the pager on page 1).
                if not page.next_from or page.next_from == cursor:
                    last_next = None
                    break
                stagnant_pages += 1
                if stagnant_pages >= self.STAGNANT_HARD_CAP:
                    break
                cursor = page.next_from
                continue
            if len(fetched_posts) >= target:
                # Keep last_next so the UI can request the following page.
                break
            if new_in_page == 0:
                stagnant_pages += 1
            else:
                stagnant_pages = 0
            if not page.next_from:
                last_next = None
                break
            if page.next_from == cursor:
                last_next = None
                break
            # Cursor advances but yields only duplicates — keep scanning until
            # the hard cap so deep pagination still fills the next UI page.
            if stagnant_pages >= self.STAGNANT_HARD_CAP:
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
