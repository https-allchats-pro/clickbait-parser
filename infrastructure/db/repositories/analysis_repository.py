from __future__ import annotations

import json
import time
from dataclasses import asdict
from typing import Any

from analysis.models import ClickbaitAnalysis, ClickbaitFeatures


class AnalysisRepository:
    """SQLite persistence for clickbait analysis results."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def save(self, analysis: ClickbaitAnalysis) -> None:
        self.save_many([analysis])

    def save_many(self, analyses: list[ClickbaitAnalysis]) -> None:
        if not analyses:
            return
        now = int(time.time())
        try:
            self._conn.execute("BEGIN")
            for analysis in analyses:
                self._upsert_one(analysis, now=now)
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def get_by_post_id(self, post_id: int) -> ClickbaitAnalysis | None:
        row = self._conn.execute(
            "SELECT * FROM post_analysis WHERE post_id = ?",
            (post_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_analysis(row)

    def get_latest(self, limit: int = 100) -> list[ClickbaitAnalysis]:
        rows = self._conn.execute(
            """
            SELECT * FROM post_analysis
            ORDER BY analyzed_at DESC, id DESC
            LIMIT ?
            """,
            (max(0, int(limit)),),
        ).fetchall()
        return [self._row_to_analysis(row) for row in rows]

    def get_clickbait(self, limit: int = 100) -> list[ClickbaitAnalysis]:
        rows = self._conn.execute(
            """
            SELECT * FROM post_analysis
            WHERE is_clickbait = 1
            ORDER BY score DESC, analyzed_at DESC
            LIMIT ?
            """,
            (max(0, int(limit)),),
        ).fetchall()
        return [self._row_to_analysis(row) for row in rows]

    def _upsert_one(self, analysis: ClickbaitAnalysis, *, now: int) -> None:
        features_json = json.dumps(asdict(analysis.features), ensure_ascii=False)
        reasons_json = json.dumps(list(analysis.reasons), ensure_ascii=False)
        self._conn.execute(
            """
            INSERT INTO post_analysis (
                post_id, score, is_clickbait, features_json, reasons_json, analyzed_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(post_id) DO UPDATE SET
                score = excluded.score,
                is_clickbait = excluded.is_clickbait,
                features_json = excluded.features_json,
                reasons_json = excluded.reasons_json,
                analyzed_at = excluded.analyzed_at
            """,
            (
                int(analysis.post_id),
                float(analysis.score),
                1 if analysis.is_clickbait else 0,
                features_json,
                reasons_json,
                now,
            ),
        )

    @staticmethod
    def _row_to_analysis(row: Any) -> ClickbaitAnalysis:
        features_raw = json.loads(row["features_json"] or "{}")
        reasons_raw = json.loads(row["reasons_json"] or "[]")
        features = ClickbaitFeatures(
            has_external_link=bool(features_raw.get("has_external_link")),
            has_continuation_phrase=bool(features_raw.get("has_continuation_phrase")),
            has_curiosity_phrase=bool(features_raw.get("has_curiosity_phrase")),
            has_cta_phrase=bool(features_raw.get("has_cta_phrase")),
            has_ellipsis=bool(features_raw.get("has_ellipsis")),
            has_excessive_exclamation=bool(features_raw.get("has_excessive_exclamation")),
            has_caps=bool(features_raw.get("has_caps")),
            has_emojis=bool(features_raw.get("has_emojis")),
            short_text_with_link=bool(features_raw.get("short_text_with_link")),
            link_near_cta=bool(features_raw.get("link_near_cta")),
        )
        reasons = [str(item) for item in reasons_raw] if isinstance(reasons_raw, list) else []
        return ClickbaitAnalysis(
            post_id=int(row["post_id"]),
            score=float(row["score"]),
            is_clickbait=bool(row["is_clickbait"]),
            reasons=reasons,
            features=features,
        )
