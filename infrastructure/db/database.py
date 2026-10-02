from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    provider_user_id INTEGER NOT NULL,
    first_name TEXT,
    last_name TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(provider, provider_user_id)
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    owner_id INTEGER NOT NULL,
    post_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    date INTEGER,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    reposts INTEGER DEFAULT 0,
    views INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(source, owner_id, post_id)
);

CREATE TABLE IF NOT EXISTS post_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    position INTEGER,
    FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE,
    UNIQUE(post_id, url)
);

CREATE INDEX IF NOT EXISTS idx_posts_source_owner
ON posts(source, owner_id);

CREATE INDEX IF NOT EXISTS idx_posts_date
ON posts(date);

CREATE TABLE IF NOT EXISTS post_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL UNIQUE,
    score REAL NOT NULL,
    is_clickbait INTEGER NOT NULL,
    features_json TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    analyzed_at INTEGER NOT NULL,
    FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_post_analysis_clickbait
ON post_analysis(is_clickbait);

CREATE INDEX IF NOT EXISTS idx_post_analysis_score
ON post_analysis(score);

CREATE TABLE IF NOT EXISTS post_labels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL UNIQUE,
    label TEXT NOT NULL,
    note TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY(post_id) REFERENCES posts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_post_labels_label
ON post_labels(label);
"""


def default_db_path() -> Path:
    """Prefer project-local data/app.sqlite3; fall back to ~/.clickbait-parser."""
    from app.runtime_paths import default_db_path as _default_db_path

    return _default_db_path()


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path is not None else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
