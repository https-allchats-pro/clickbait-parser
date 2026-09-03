from __future__ import annotations

import time
from typing import Any

from domain.posts import CatalogPost, PostLink, UpsertResult


class PostRepository:
    """SQLite persistence for catalog posts + links. No VK-specific logic."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def upsert(self, post: CatalogPost) -> int:
        result = self.upsert_many([post])
        loaded = self.get(post.source, post.owner_id, post.post_id)
        if loaded is None or loaded.id is None:
            raise RuntimeError("upsert did not persist post")
        _ = result
        return int(loaded.id)

    def upsert_many(self, posts: list[CatalogPost]) -> UpsertResult:
        inserted = updated = unchanged = 0
        now = int(time.time())

        try:
            self._conn.execute("BEGIN")
            for post in posts:
                outcome = self._upsert_one(post, now=now)
                if outcome == "inserted":
                    inserted += 1
                elif outcome == "updated":
                    updated += 1
                else:
                    unchanged += 1
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        return UpsertResult(inserted=inserted, updated=updated, unchanged=unchanged)

    def get(self, source: str, owner_id: int, post_id: int) -> CatalogPost | None:
        row = self._conn.execute(
            """
            SELECT * FROM posts
            WHERE source = ? AND owner_id = ? AND post_id = ?
            """,
            (source, owner_id, post_id),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_post(row)

    def get_latest(self, limit: int = 100) -> list[CatalogPost]:
        rows = self._conn.execute(
            """
            SELECT * FROM posts
            ORDER BY date DESC, id DESC
            LIMIT ?
            """,
            (max(0, int(limit)),),
        ).fetchall()
        return [self._row_to_post(row) for row in rows]

    def delete(self, source: str, owner_id: int, post_id: int) -> None:
        self._conn.execute(
            """
            DELETE FROM posts
            WHERE source = ? AND owner_id = ? AND post_id = ?
            """,
            (source, owner_id, post_id),
        )
        self._conn.commit()

    def _upsert_one(self, post: CatalogPost, *, now: int) -> str:
        date_ts = int(post.date.timestamp()) if post.date is not None else None
        existing = self._conn.execute(
            """
            SELECT id, text, date, likes, comments, reposts, views
            FROM posts
            WHERE source = ? AND owner_id = ? AND post_id = ?
            """,
            (post.source, post.owner_id, post.post_id),
        ).fetchone()

        if existing is None:
            cursor = self._conn.execute(
                """
                INSERT INTO posts (
                    source, owner_id, post_id, text, date,
                    likes, comments, reposts, views,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    post.source,
                    post.owner_id,
                    post.post_id,
                    post.text,
                    date_ts,
                    post.likes,
                    post.comments,
                    post.reposts,
                    post.views,
                    now,
                    now,
                ),
            )
            row_id = int(cursor.lastrowid)
            self._replace_links(row_id, post.links)
            return "inserted"

        row_id = int(existing["id"])
        same = (
            str(existing["text"] or "") == post.text
            and int(existing["date"] or 0) == int(date_ts or 0)
            and int(existing["likes"] or 0) == post.likes
            and int(existing["comments"] or 0) == post.comments
            and int(existing["reposts"] or 0) == post.reposts
            and int(existing["views"] or 0) == post.views
            and self._links_equal(row_id, post.links)
        )
        if same:
            return "unchanged"

        self._conn.execute(
            """
            UPDATE posts
            SET text = ?, date = ?, likes = ?, comments = ?,
                reposts = ?, views = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                post.text,
                date_ts,
                post.likes,
                post.comments,
                post.reposts,
                post.views,
                now,
                row_id,
            ),
        )
        self._replace_links(row_id, post.links)
        return "updated"

    def _links_equal(self, post_row_id: int, links: list[PostLink]) -> bool:
        rows = self._conn.execute(
            """
            SELECT url, position FROM post_links
            WHERE post_id = ?
            ORDER BY COALESCE(position, 0), id
            """,
            (post_row_id,),
        ).fetchall()
        current = [(str(r["url"]), r["position"]) for r in rows]
        expected = [(link.url, link.position) for link in links]
        return current == expected

    def _replace_links(self, post_row_id: int, links: list[PostLink]) -> None:
        self._conn.execute("DELETE FROM post_links WHERE post_id = ?", (post_row_id,))
        for link in links:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO post_links (post_id, url, position)
                VALUES (?, ?, ?)
                """,
                (post_row_id, link.url, link.position),
            )

    def _load_links(self, post_row_id: int) -> list[PostLink]:
        rows = self._conn.execute(
            """
            SELECT url, position FROM post_links
            WHERE post_id = ?
            ORDER BY COALESCE(position, 0), id
            """,
            (post_row_id,),
        ).fetchall()
        return [
            PostLink(url=str(row["url"]), position=row["position"])
            for row in rows
        ]

    def _row_to_post(self, row: Any) -> CatalogPost:
        from datetime import UTC, datetime

        date_ts = int(row["date"] or 0)
        date = datetime.fromtimestamp(date_ts, tz=UTC) if date_ts else datetime.fromtimestamp(0, tz=UTC)
        row_id = int(row["id"])
        return CatalogPost(
            id=row_id,
            source=str(row["source"]),
            owner_id=int(row["owner_id"]),
            post_id=int(row["post_id"]),
            text=str(row["text"] or ""),
            date=date,
            likes=int(row["likes"] or 0),
            comments=int(row["comments"] or 0),
            reposts=int(row["reposts"] or 0),
            views=int(row["views"] or 0),
            links=self._load_links(row_id),
        )
