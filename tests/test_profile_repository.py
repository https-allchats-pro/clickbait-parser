from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.auth.models import VKProfile
from infrastructure.db.database import init_schema
from infrastructure.db.repositories.profile_repository import ProfileRepository


class ProfileRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        path = Path(self._tmp.name) / "test.db"
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        init_schema(self.conn)
        self.repo = ProfileRepository(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_create_or_update_inserts(self) -> None:
        profile_id = self.repo.create_or_update(
            VKProfile(
                provider="vk",
                provider_user_id=42,
                first_name="Ada",
                last_name="Lovelace",
            )
        )
        got = self.repo.get(profile_id)
        assert got is not None
        self.assertEqual(got.id, profile_id)
        self.assertEqual(got.provider, "vk")
        self.assertEqual(got.provider_user_id, 42)
        self.assertEqual(got.first_name, "Ada")
        self.assertEqual(got.last_name, "Lovelace")

    def test_create_or_update_updates_same_provider_user(self) -> None:
        first_id = self.repo.create_or_update(
            VKProfile(provider="vk", provider_user_id=7, first_name="A", last_name="B")
        )
        second_id = self.repo.create_or_update(
            VKProfile(provider="vk", provider_user_id=7, first_name="Ann", last_name="Bee")
        )
        self.assertEqual(first_id, second_id)
        all_profiles = self.repo.get_all()
        self.assertEqual(len(all_profiles), 1)
        self.assertEqual(all_profiles[0].first_name, "Ann")
        self.assertEqual(all_profiles[0].last_name, "Bee")

    def test_get_missing_returns_none(self) -> None:
        self.assertIsNone(self.repo.get(999))

    def test_get_all_ordered(self) -> None:
        self.repo.create_or_update(VKProfile(provider="vk", provider_user_id=1))
        self.repo.create_or_update(VKProfile(provider="telegram", provider_user_id=2))
        ids = [p.provider_user_id for p in self.repo.get_all()]
        self.assertEqual(ids, [1, 2])

    def test_delete(self) -> None:
        profile_id = self.repo.create_or_update(
            VKProfile(provider="vk", provider_user_id=99, first_name="X")
        )
        self.repo.delete(profile_id)
        self.assertIsNone(self.repo.get(profile_id))
        self.assertEqual(self.repo.get_all(), [])


if __name__ == "__main__":
    unittest.main()
