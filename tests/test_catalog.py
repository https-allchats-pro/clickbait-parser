from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

from app.catalog.service import CatalogService
from domain.posts import CatalogPage, CatalogPost, PostLink, SOURCE_VK_CATALOG
from infrastructure.db.database import init_schema
from infrastructure.db.repositories.post_repository import PostRepository
from infrastructure.vk.catalog_mapper import (
    CatalogMapperError,
    VKCatalogPostMapper,
    iter_raw_wall_posts,
)


FIXTURE = Path(__file__).parent / "fixtures" / "catalog_get_search_top.json"


class MapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mapper = VKCatalogPostMapper()
        self.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_fixture_maps_three_posts(self) -> None:
        posts = self.mapper.map_response(self.fixture)
        self.assertEqual(len(posts), 3)
        self.assertEqual(posts[0].source, SOURCE_VK_CATALOG)
        self.assertEqual(posts[0].owner_id, -100)
        self.assertEqual(posts[0].post_id, 1)
        self.assertIn("Обычный пост", posts[0].text)
        self.assertEqual(posts[0].likes, 10)
        urls = {link.url for link in posts[0].links}
        self.assertIn("https://example.com/structured", urls)
        self.assertIn("https://example.com/a", urls)

    def test_empty_text_repost_uses_copy_history(self) -> None:
        posts = {p.post_id: p for p in self.mapper.map_response(self.fixture)}
        self.assertIn("Репостнутый оригинал", posts[2].text)
        self.assertTrue(any("news.example.org" in link.url for link in posts[2].links))

    def test_multiple_urls_deduped(self) -> None:
        posts = {p.post_id: p for p in self.mapper.map_response(self.fixture)}
        urls = [link.url for link in posts[3].links]
        self.assertEqual(urls.count("https://a.example/1"), 1)
        self.assertIn("https://b.example/2", urls)
        self.assertIn("https://docs.example/file.pdf", urls)

    def test_missing_optional_fields(self) -> None:
        post = self.mapper.map(
            {"id": 7, "owner_id": -1, "date": 1, "text": "", "post_type": "post"}
        )
        self.assertEqual(post.likes, 0)
        self.assertEqual(post.views, 0)
        self.assertEqual(post.links, [])

    def test_photo_attachment_not_separate_post(self) -> None:
        posts = self.mapper.map_response(self.fixture)
        ids = {(p.owner_id, p.post_id) for p in posts}
        self.assertNotIn((-100, 999001), ids)
        self.assertEqual(len(posts), 3)

    def test_malformed_raises(self) -> None:
        with self.assertRaises(CatalogMapperError):
            self.mapper.map({"hello": "world"})
        with self.assertRaises(CatalogMapperError):
            self.mapper.map("not-a-dict")

    def test_iter_skips_non_posts(self) -> None:
        raw = iter_raw_wall_posts({"profiles": [{"id": 1, "first_name": "A"}], "items": []})
        self.assertEqual(raw, [])


class PostRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        path = Path(self._tmp.name) / "t.db"
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        init_schema(self.conn)
        self.repo = PostRepository(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def _sample(self, **overrides: object) -> CatalogPost:
        data = dict(
            source=SOURCE_VK_CATALOG,
            owner_id=-10,
            post_id=55,
            text="hello",
            date=datetime.fromtimestamp(1_700_000_000, tz=UTC),
            likes=1,
            comments=0,
            reposts=0,
            views=10,
            links=[PostLink(url="https://example.com", position=0)],
        )
        data.update(overrides)
        return CatalogPost(**data)  # type: ignore[arg-type]

    def test_insert_get_and_links(self) -> None:
        row_id = self.repo.upsert(self._sample())
        got = self.repo.get(SOURCE_VK_CATALOG, -10, 55)
        assert got is not None
        self.assertEqual(got.id, row_id)
        self.assertEqual(got.text, "hello")
        self.assertEqual(len(got.links), 1)
        self.assertEqual(got.links[0].url, "https://example.com")

    def test_duplicate_unchanged(self) -> None:
        post = self._sample()
        first = self.repo.upsert_many([post])
        second = self.repo.upsert_many([post])
        self.assertEqual(first.inserted, 1)
        self.assertEqual(second.unchanged, 1)
        self.assertEqual(second.inserted, 0)
        self.assertEqual(len(self.repo.get_latest(10)), 1)

    def test_update_when_stats_change(self) -> None:
        self.repo.upsert(self._sample(likes=1))
        result = self.repo.upsert_many([self._sample(likes=99, text="hello")])
        self.assertEqual(result.updated, 1)
        got = self.repo.get(SOURCE_VK_CATALOG, -10, 55)
        assert got is not None
        self.assertEqual(got.likes, 99)

    def test_bulk_upsert(self) -> None:
        posts = [
            self._sample(post_id=1, owner_id=-1),
            self._sample(post_id=2, owner_id=-2, links=[]),
        ]
        result = self.repo.upsert_many(posts)
        self.assertEqual(result.inserted, 2)
        self.assertEqual(len(self.repo.get_latest(10)), 2)

    def test_get_latest_order(self) -> None:
        self.repo.upsert(self._sample(post_id=1, date=datetime.fromtimestamp(100, tz=UTC)))
        self.repo.upsert(self._sample(post_id=2, date=datetime.fromtimestamp(200, tz=UTC)))
        latest = self.repo.get_latest(1)
        self.assertEqual(latest[0].post_id, 2)

    def test_cascade_delete_links(self) -> None:
        self.repo.upsert(self._sample())
        self.repo.delete(SOURCE_VK_CATALOG, -10, 55)
        self.assertIsNone(self.repo.get(SOURCE_VK_CATALOG, -10, 55))
        count = self.conn.execute("SELECT COUNT(*) AS c FROM post_links").fetchone()["c"]
        self.assertEqual(count, 0)


class CatalogServiceTests(unittest.TestCase):
    def test_collect_upserts_client_page(self) -> None:
        client = MagicMock()
        posts_repo = MagicMock()
        page_posts = [
            CatalogPost(
                source=SOURCE_VK_CATALOG,
                owner_id=-1,
                post_id=1,
                text="a",
                date=datetime.fromtimestamp(1, tz=UTC),
            )
        ]
        loaded = CatalogPost(
            source=SOURCE_VK_CATALOG,
            owner_id=-1,
            post_id=1,
            text="a",
            date=datetime.fromtimestamp(1, tz=UTC),
            id=42,
        )
        client.get_search_top.return_value = CatalogPage(posts=page_posts, next_from=None)
        posts_repo.upsert_many.return_value = type(
            "R", (), {"inserted": 1, "updated": 0, "unchanged": 0}
        )()
        posts_repo.get.return_value = loaded

        service = CatalogService(client=client, posts=posts_repo)
        result = service.collect(count=100)
        client.get_search_top.assert_called_once_with(
            count=50, start_from=None, query=None, start_time=None, end_time=None
        )
        posts_repo.upsert_many.assert_called_once_with(page_posts)
        self.assertEqual(result.fetched, 1)
        self.assertEqual(result.upsert.inserted, 1)
        self.assertEqual(result.posts[0].id, 42)

    def test_collect_paginates_until_count(self) -> None:
        client = MagicMock()
        posts_repo = MagicMock()
        posts_repo.upsert_many.side_effect = [
            type("R", (), {"inserted": 2, "updated": 0, "unchanged": 0})(),
            type("R", (), {"inserted": 1, "updated": 0, "unchanged": 0})(),
        ]

        def _page(
            *,
            count: int,
            start_from: str | None = None,
            query: str | None = None,
            start_time: int | None = None,
            end_time: int | None = None,
        ) -> CatalogPage:
            _ = (start_time, end_time)
            if start_from is None:
                return CatalogPage(
                    posts=[
                        CatalogPost(
                            source=SOURCE_VK_CATALOG,
                            owner_id=-1,
                            post_id=i,
                            text=f"x{i}",
                            date=datetime.fromtimestamp(1, tz=UTC),
                        )
                        for i in range(2)  # partial first page → need page 2
                    ],
                    next_from="n1",
                )
            return CatalogPage(
                posts=[
                    CatalogPost(
                        source=SOURCE_VK_CATALOG,
                        owner_id=-1,
                        post_id=99,
                        text="y",
                        date=datetime.fromtimestamp(2, tz=UTC),
                    )
                ],
                next_from=None,
            )

        def _get(source: str, owner_id: int, post_id: int) -> CatalogPost:
            return CatalogPost(
                source=source,
                owner_id=owner_id,
                post_id=post_id,
                text=f"x{post_id}" if post_id != 99 else "y",
                date=datetime.fromtimestamp(1, tz=UTC),
                id=post_id + 100,
            )

        client.get_search_top.side_effect = _page
        posts_repo.get.side_effect = _get
        service = CatalogService(client=client, posts=posts_repo)
        # page_size is capped to VK's ~20; request 2 to exercise multi-page.
        result = service.collect(count=3, page_size=2, pages=5)
        self.assertEqual(result.fetched, 3)
        self.assertEqual(len(result.posts), 3)
        self.assertEqual(client.get_search_top.call_count, 2)
        # VK page size stays fixed across pages (do not shrink count near the end).
        self.assertEqual(client.get_search_top.call_args_list[0].kwargs["count"], 50)
        self.assertEqual(client.get_search_top.call_args_list[1].kwargs["count"], 50)

    def test_collect_continues_when_first_page_is_partial(self) -> None:
        client = MagicMock()
        posts_repo = MagicMock()
        posts_repo.upsert_many.return_value = type(
            "R", (), {"inserted": 1, "updated": 0, "unchanged": 0}
        )()

        pages = [
            CatalogPage(
                posts=[
                    CatalogPost(
                        source=SOURCE_VK_CATALOG,
                        owner_id=-1,
                        post_id=i,
                        text=f"x{i}",
                        date=datetime.fromtimestamp(1, tz=UTC),
                    )
                    for i in range(20)
                ],
                next_from="n1",
            ),
            CatalogPage(
                posts=[
                    CatalogPost(
                        source=SOURCE_VK_CATALOG,
                        owner_id=-1,
                        post_id=100 + i,
                        text=f"y{i}",
                        date=datetime.fromtimestamp(2, tz=UTC),
                    )
                    for i in range(20)
                ],
                next_from=None,
            ),
        ]
        client.get_search_top.side_effect = pages

        def _get(source: str, owner_id: int, post_id: int) -> CatalogPost:
            return CatalogPost(
                source=source,
                owner_id=owner_id,
                post_id=post_id,
                text=f"post-{post_id}",
                date=datetime.fromtimestamp(1, tz=UTC),
                id=post_id,
            )

        posts_repo.get.side_effect = _get
        service = CatalogService(client=client, posts=posts_repo)
        result = service.collect(count=30, page_size=100, pages=1)
        self.assertEqual(result.fetched, 30)
        self.assertEqual(client.get_search_top.call_count, 2)
        self.assertEqual(client.get_search_top.call_args_list[0].kwargs["count"], 50)
        self.assertEqual(client.get_search_top.call_args_list[1].kwargs["count"], 50)

    def test_collect_stops_after_stagnant_duplicate_pages(self) -> None:
        client = MagicMock()
        posts_repo = MagicMock()
        posts_repo.upsert_many.return_value = type(
            "R", (), {"inserted": 0, "updated": 0, "unchanged": 1}
        )()
        dup = CatalogPost(
            source=SOURCE_VK_CATALOG,
            owner_id=-1,
            post_id=1,
            text="same",
            date=datetime.fromtimestamp(1, tz=UTC),
            id=1,
        )
        client.get_search_top.side_effect = [
            CatalogPage(posts=[dup], next_from=f"n{i}")
            for i in range(1, CatalogService.STAGNANT_HARD_CAP + 5)
        ]
        posts_repo.get.return_value = dup
        service = CatalogService(client=client, posts=posts_repo)
        result = service.collect(count=50, pages=20)
        self.assertEqual(result.fetched, 1)
        # first page yields 1, then duplicate-only pages until STAGNANT_HARD_CAP
        self.assertEqual(
            client.get_search_top.call_count,
            1 + CatalogService.STAGNANT_HARD_CAP,
        )
        # Cursor must survive so the GUI can keep paginating.
        self.assertIsNotNone(result.next_from)

    def test_collect_keeps_cursor_on_empty_mapped_page(self) -> None:
        client = MagicMock()
        posts_repo = MagicMock()
        posts_repo.upsert_many.return_value = type(
            "R", (), {"inserted": 1, "updated": 0, "unchanged": 0}
        )()

        good = CatalogPost(
            source=SOURCE_VK_CATALOG,
            owner_id=-1,
            post_id=7,
            text="ok",
            date=datetime.fromtimestamp(1, tz=UTC),
            id=7,
        )

        def _page(
            *,
            count: int,
            start_from: str | None = None,
            query: str | None = None,
            start_time: int | None = None,
            end_time: int | None = None,
        ) -> CatalogPage:
            _ = (count, query, start_time, end_time)
            if start_from is None:
                return CatalogPage(posts=[], next_from="n1")
            return CatalogPage(posts=[good], next_from="n2")

        def _get(source: str, owner_id: int, post_id: int) -> CatalogPost:
            return good

        client.get_search_top.side_effect = _page
        posts_repo.get.side_effect = _get
        service = CatalogService(client=client, posts=posts_repo)
        result = service.collect(count=1, pages=5)
        self.assertEqual(result.fetched, 1)
        self.assertEqual(result.next_from, "n2")
        self.assertEqual(client.get_search_top.call_count, 2)

    def test_collect_keeps_same_text_from_different_posts(self) -> None:
        client = MagicMock()
        posts_repo = MagicMock()
        posts_repo.upsert_many.return_value = type(
            "R", (), {"inserted": 3, "updated": 0, "unchanged": 0}
        )()
        a = CatalogPost(
            source=SOURCE_VK_CATALOG,
            owner_id=-1,
            post_id=1,
            text="Повтор текста",
            date=datetime.fromtimestamp(1, tz=UTC),
            id=1,
        )
        b = CatalogPost(
            source=SOURCE_VK_CATALOG,
            owner_id=-2,
            post_id=2,
            text="  повтор   текста ",
            date=datetime.fromtimestamp(2, tz=UTC),
            id=2,
        )
        c = CatalogPost(
            source=SOURCE_VK_CATALOG,
            owner_id=-3,
            post_id=3,
            text="Уникальный",
            date=datetime.fromtimestamp(3, tz=UTC),
            id=3,
        )
        client.get_search_top.return_value = CatalogPage(posts=[a, b, c], next_from=None)

        def _get(source: str, owner_id: int, post_id: int) -> CatalogPost:
            return {1: a, 2: b, 3: c}[post_id]

        posts_repo.get.side_effect = _get
        service = CatalogService(client=client, posts=posts_repo)
        result = service.collect(count=10)
        self.assertEqual(result.fetched, 3)
        self.assertEqual([p.post_id for p in result.posts], [1, 2, 3])

    def test_collect_preserves_next_from_when_target_reached(self) -> None:
        client = MagicMock()
        posts_repo = MagicMock()
        posts_repo.upsert_many.return_value = type(
            "R", (), {"inserted": 2, "updated": 0, "unchanged": 0}
        )()
        posts = [
            CatalogPost(
                source=SOURCE_VK_CATALOG,
                owner_id=-1,
                post_id=i,
                text=f"post-{i}",
                date=datetime.fromtimestamp(i, tz=UTC),
                id=i,
            )
            for i in range(3)
        ]
        client.get_search_top.return_value = CatalogPage(posts=posts, next_from="cursor-next")

        def _get(source: str, owner_id: int, post_id: int) -> CatalogPost:
            return posts[post_id]

        posts_repo.get.side_effect = _get
        service = CatalogService(client=client, posts=posts_repo)
        result = service.collect(count=2)
        self.assertEqual(result.fetched, 2)
        self.assertEqual(result.next_from, "cursor-next")
        self.assertTrue(result.has_more)

        client = MagicMock()
        posts_repo = MagicMock()
        posts_repo.upsert_many.return_value = type(
            "R", (), {"inserted": 1, "updated": 0, "unchanged": 0}
        )()
        a = CatalogPost(
            source=SOURCE_VK_CATALOG,
            owner_id=-1,
            post_id=1,
            text="Уже видели",
            date=datetime.fromtimestamp(1, tz=UTC),
            id=1,
        )
        b = CatalogPost(
            source=SOURCE_VK_CATALOG,
            owner_id=-2,
            post_id=2,
            text="Новый пост",
            date=datetime.fromtimestamp(2, tz=UTC),
            id=2,
        )
        client.get_search_top.return_value = CatalogPage(posts=[a, b], next_from=None)

        def _get(source: str, owner_id: int, post_id: int) -> CatalogPost:
            return {1: a, 2: b}[post_id]

        posts_repo.get.side_effect = _get
        service = CatalogService(client=client, posts=posts_repo)
        result = service.collect(
            count=10,
            start_from="n1",
            exclude_texts={"уже видели"},  # ignored: text dedupe removed
        )
        self.assertEqual(result.fetched, 2)
        self.assertEqual([p.post_id for p in result.posts], [1, 2])
        self.assertIsNone(result.next_from)
        client.get_search_top.assert_called_once_with(
            count=50, start_from="n1", query=None, start_time=None, end_time=None
        )

    def test_collect_without_persist_uses_ephemeral_ids(self) -> None:
        client = MagicMock()
        page_posts = [
            CatalogPost(
                source=SOURCE_VK_CATALOG,
                owner_id=-1,
                post_id=7,
                text="memory only",
                date=datetime.fromtimestamp(1, tz=UTC),
            )
        ]
        client.get_search_top.return_value = CatalogPage(posts=page_posts, next_from=None)
        service = CatalogService(client=client, posts=None, persist_posts=False)
        result = service.collect(count=10)
        self.assertEqual(result.fetched, 1)
        self.assertEqual(result.upsert.inserted, 0)
        self.assertEqual(result.posts[0].post_id, 7)
        self.assertIsNotNone(result.posts[0].id)
        self.assertLess(result.posts[0].id, 0)


if __name__ == "__main__":
    unittest.main()
