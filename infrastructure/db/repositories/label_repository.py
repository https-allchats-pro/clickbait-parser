from __future__ import annotations

import time
from typing import Any

from domain.dataset import DatasetLabel, PostLabel


class LabelRepository:
    """SQLite persistence for human ground-truth labels."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def save(self, label: PostLabel) -> PostLabel:
        now = int(time.time())
        created_at = label.created_at or now
        updated_at = now
        note = label.note

        existing = self.get_by_post_id(label.post_id)
        if existing is None:
            cursor = self._conn.execute(
                """
                INSERT INTO post_labels (post_id, label, note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (label.post_id, label.label.value, note, created_at, updated_at),
            )
            self._conn.commit()
            return PostLabel(
                id=int(cursor.lastrowid),
                post_id=label.post_id,
                label=label.label,
                note=note,
                created_at=created_at,
                updated_at=updated_at,
            )

        self._conn.execute(
            """
            UPDATE post_labels
            SET label = ?, note = ?, updated_at = ?
            WHERE post_id = ?
            """,
            (label.label.value, note, updated_at, label.post_id),
        )
        self._conn.commit()
        return PostLabel(
            id=existing.id,
            post_id=label.post_id,
            label=label.label,
            note=note,
            created_at=existing.created_at,
            updated_at=updated_at,
        )

    def get_by_post_id(self, post_id: int) -> PostLabel | None:
        row = self._conn.execute(
            "SELECT * FROM post_labels WHERE post_id = ?",
            (post_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_label(row)

    def list_by_label(self, label: DatasetLabel, limit: int = 100) -> list[PostLabel]:
        rows = self._conn.execute(
            """
            SELECT * FROM post_labels
            WHERE label = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (label.value, max(0, int(limit))),
        ).fetchall()
        return [self._row_to_label(row) for row in rows]

    def count_by_label(self) -> dict[DatasetLabel, int]:
        counts = {label: 0 for label in DatasetLabel}
        rows = self._conn.execute(
            "SELECT label, COUNT(*) AS c FROM post_labels GROUP BY label"
        ).fetchall()
        for row in rows:
            try:
                key = DatasetLabel(str(row["label"]))
            except ValueError:
                continue
            counts[key] = int(row["c"])
        return counts

    def count_labeled(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS c FROM post_labels").fetchone()
        return int(row["c"] if row else 0)

    def list_all(self, limit: int | None = None) -> list[PostLabel]:
        if limit is None:
            rows = self._conn.execute(
                "SELECT * FROM post_labels ORDER BY id ASC"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM post_labels ORDER BY id ASC LIMIT ?",
                (max(0, int(limit)),),
            ).fetchall()
        return [self._row_to_label(row) for row in rows]

    @staticmethod
    def _row_to_label(row: Any) -> PostLabel:
        return PostLabel(
            id=int(row["id"]),
            post_id=int(row["post_id"]),
            label=DatasetLabel(str(row["label"])),
            note=row["note"],
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
        )
