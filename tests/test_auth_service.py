from __future__ import annotations

import sqlite3
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.auth.models import VKProfile
from app.auth.service import AuthService
from infrastructure.credentials.store import FileCredentialStore
from infrastructure.db.database import init_schema
from infrastructure.db.repositories.profile_repository import ProfileRepository


@dataclass
class FakeUser:
    user_id: int
    first_name: str | None
    last_name: str | None


class FakeVKClient:
    def __init__(self) -> None:
        self.authenticate_calls: list[str] = []
        self.closed = False
        self._user = FakeUser(user_id=1001, first_name="Ivan", last_name="Petrov")

    def authenticate(self, *, method: str = "qr") -> FakeUser:
        self.authenticate_calls.append(method)
        return self._user

    def get_current_user(self) -> FakeUser:
        return self._user

    def get_credentials(self) -> dict[str, Any]:
        return {
            "device_id": "1001",
            "user_id": "1001",
            "auth_method": "qr",
            "access_token": "secret-token",
            "refresh_token": "",
            "token_expires_at": 0,
            "state_instance": "authorized",
        }

    def close(self) -> None:
        self.closed = True


class AuthServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        db_path = Path(self._tmp.name) / "test.db"
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        init_schema(self.conn)
        self.repo = ProfileRepository(self.conn)
        self.creds = FileCredentialStore(Path(self._tmp.name) / "creds")
        self.vk = FakeVKClient()
        self.service = AuthService(
            vk_client=self.vk,
            profiles=self.repo,
            credentials=self.creds,
        )

    def tearDown(self) -> None:
        self.conn.close()

    def test_login_vk_persists_profile_and_credentials(self) -> None:
        profile = self.service.login_vk(method="qr")
        self.assertEqual(self.vk.authenticate_calls, ["qr"])
        self.assertTrue(self.vk.closed)
        self.assertIsNotNone(profile.id)
        self.assertEqual(profile.provider, "vk")
        self.assertEqual(profile.provider_user_id, 1001)
        self.assertEqual(profile.first_name, "Ivan")
        self.assertEqual(profile.last_name, "Petrov")

        stored = self.creds.load("vk", 1001)
        assert stored is not None
        self.assertEqual(stored["access_token"], "secret-token")
        self.assertEqual(stored["auth_method"], "qr")

        # Password must never appear in credentials payload from client.
        self.assertNotIn("password", stored)

    def test_get_profiles_and_get_profile(self) -> None:
        created = self.service.login_vk()
        all_profiles = self.service.get_profiles()
        self.assertEqual(len(all_profiles), 1)
        assert created.id is not None
        got = self.service.get_profile(created.id)
        assert got is not None
        self.assertEqual(got.provider_user_id, 1001)

    def test_logout_removes_profile_and_credentials(self) -> None:
        created = self.service.login_vk()
        assert created.id is not None
        self.service.logout(created.id)
        self.assertIsNone(self.service.get_profile(created.id))
        self.assertIsNone(self.creds.load("vk", 1001))
        self.assertEqual(self.service.get_profiles(), [])

    def test_logout_missing_is_noop(self) -> None:
        self.service.logout(404)


if __name__ == "__main__":
    unittest.main()
