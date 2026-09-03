from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PostLink:
    url: str
    position: int | None = None


@dataclass
class CatalogPost:
    """Provider-agnostic catalog post (no VK raw dicts, no SQL)."""

    source: str
    owner_id: int
    post_id: int
    text: str
    date: datetime
    likes: int = 0
    comments: int = 0
    reposts: int = 0
    views: int = 0
    links: list[PostLink] = field(default_factory=list)
    id: int | None = None  # local SQLite row id when loaded


SOURCE_VK_CATALOG = "vk_catalog"


def post_text_key(text: str) -> str:
    """Normalize post body for uniqueness (collect / UI dedupe)."""
    return " ".join((text or "").casefold().split())


@dataclass
class CatalogPage:
    posts: list[CatalogPost]
    next_from: str | None = None


@dataclass
class UpsertResult:
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0

    @property
    def fetched(self) -> int:
        return self.inserted + self.updated + self.unchanged


@dataclass
class CollectResult:
    fetched: int
    upsert: UpsertResult
    next_from: str | None = None
    pages: int = 1
    posts: list[CatalogPost] = field(default_factory=list)
