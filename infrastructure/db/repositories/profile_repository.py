from __future__ import annotations

import time
from typing import Any

from app.auth.models import VKProfile


class ProfileRepository:
    """SQLite persistence for provider profiles. No VK-specific logic."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def create_or_update(self, profile: VKProfile) -> int:
        now = int(time.time())
        row = self._conn.execute(
            """
            SELECT id FROM profiles
            WHERE provider = ? AND provider_user_id = ?
            """,
            (profile.provider, profile.provider_user_id),
        ).fetchone()

        if row is None:
            cursor = self._conn.execute(
                """
                INSERT INTO profiles (
                    provider, provider_user_id, first_name, last_name,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    profile.provider,
                    profile.provider_user_id,
                    profile.first_name,
                    profile.last_name,
                    now,
                    now,
                ),
            )
            self._conn.commit()
            return int(cursor.lastrowid)

        profile_id = int(row["id"])
        self._conn.execute(
            """
            UPDATE profiles
            SET first_name = ?, last_name = ?, updated_at = ?
            WHERE id = ?
            """,
            (profile.first_name, profile.last_name, now, profile_id),
        )
        self._conn.commit()
        return profile_id

    def get(self, profile_id: int) -> VKProfile | None:
        row = self._conn.execute(
            "SELECT * FROM profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_profile(row)

    def get_all(self) -> list[VKProfile]:
        rows = self._conn.execute(
            "SELECT * FROM profiles ORDER BY id ASC"
        ).fetchall()
        return [self._row_to_profile(row) for row in rows]

    def delete(self, profile_id: int) -> None:
        self._conn.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
        self._conn.commit()

    @staticmethod
    def _row_to_profile(row: Any) -> VKProfile:
        return VKProfile(
            id=int(row["id"]),
            provider=str(row["provider"]),
            provider_user_id=int(row["provider_user_id"]),
            first_name=row["first_name"],
            last_name=row["last_name"],
        )
