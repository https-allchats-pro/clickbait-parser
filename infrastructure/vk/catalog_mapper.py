from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from domain.posts import SOURCE_VK_CATALOG, CatalogPost, PostLink

_URL_RE = re.compile(r"https?://[^\s<>\[\]()\"']+", re.IGNORECASE)


class CatalogMapperError(ValueError):
    """Raised when a raw VK object cannot be mapped to CatalogPost."""


def _counter(payload: dict[str, Any], key: str) -> int:
    block = payload.get(key)
    if isinstance(block, dict):
        try:
            return int(block.get("count") or 0)
        except (TypeError, ValueError):
            return 0
    if isinstance(block, (int, float)):
        return int(block)
    return 0


def _normalize_url(url: str) -> str | None:
    text = (url or "").strip()
    if not text:
        return None
    text = text.rstrip(".,);]}>\"'")
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return text


def _add_url(urls: list[str], seen: set[str], url: str | None) -> None:
    normalized = _normalize_url(url or "")
    if not normalized:
        return
    key = normalized.rstrip("/")
    if key in seen:
        return
    seen.add(key)
    urls.append(normalized)


def extract_urls_from_post(raw: dict[str, Any]) -> list[PostLink]:
    """Collect unique URLs from structured attachments and post text."""
    ordered: list[str] = []
    seen: set[str] = set()

    attachments = raw.get("attachments")
    if isinstance(attachments, list):
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            attach_type = str(attachment.get("type") or "").strip().lower()
            if attach_type == "link":
                link = attachment.get("link")
                if isinstance(link, dict):
                    _add_url(ordered, seen, str(link.get("url") or ""))
            elif attach_type == "doc":
                doc = attachment.get("doc")
                if isinstance(doc, dict):
                    _add_url(ordered, seen, str(doc.get("url") or ""))
            elif attach_type == "video":
                video = attachment.get("video")
                if isinstance(video, dict):
                    _add_url(ordered, seen, str(video.get("url") or ""))
            elif attach_type == "photo":
                continue
            else:
                nested = attachment.get(attach_type)
                if isinstance(nested, dict) and nested.get("url"):
                    _add_url(ordered, seen, str(nested.get("url") or ""))

    text = str(raw.get("text") or "")
    for match in _URL_RE.findall(text):
        _add_url(ordered, seen, match)

    for key in ("button", "action"):
        block = raw.get(key)
        if isinstance(block, dict):
            _add_url(ordered, seen, str(block.get("url") or ""))

    return [PostLink(url=url, position=index) for index, url in enumerate(ordered)]


def looks_like_wall_post(obj: Any) -> bool:
    """True for wall posts; false for photos/users/groups nested in the payload."""
    if not isinstance(obj, dict):
        return False
    try:
        owner_id = int(obj.get("owner_id"))
        # Prefer explicit post_id when present (newsfeed wrappers).
        post_id = int(obj.get("post_id") if obj.get("post_id") is not None else obj.get("id"))
    except (TypeError, ValueError):
        return False
    if owner_id == 0 or post_id <= 0:
        return False

    post_type = str(obj.get("post_type") or "").strip().lower()
    obj_type = str(obj.get("type") or "").strip().lower()
    inner_type = str(obj.get("inner_type") or "").strip().lower()
    if post_type in {"post", "reply", "postpone", "suggest"}:
        return True
    if obj_type in {"post", "wall", "wall_wallpost"}:
        return True
    if inner_type.startswith("wall_"):
        return True
    # Legacy fixture shape: explicit wall markers without type fields.
    if "copy_history" in obj:
        return True
    if "comments" in obj and "likes" in obj and "date" in obj and "text" in obj:
        return True
    return False


def _post_key(post: dict[str, Any]) -> tuple[int, int] | None:
    try:
        owner_id = int(post["owner_id"])
        if post.get("post_id") is not None:
            post_id = int(post["post_id"])
        else:
            post_id = int(post["id"])
    except (KeyError, TypeError, ValueError):
        return None
    if owner_id == 0 or post_id <= 0:
        return None
    return owner_id, post_id


def iter_raw_wall_posts(payload: Any) -> list[dict[str, Any]]:
    """Collect unique wall-post dicts from catalog / newsfeed payloads."""
    found: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()

    def _take(post: dict[str, Any]) -> None:
        key = _post_key(post)
        if key is None or key in seen:
            return
        if not looks_like_wall_post(post):
            return
        seen.add(key)
        found.append(post)

    # Preferred path for newsfeed.search (items[]) and catalog statuses.
    if isinstance(payload, dict):
        items = payload.get("items")
        if isinstance(items, list) and items:
            for item in items:
                if isinstance(item, dict):
                    _take(item)
            if found:
                return found

        newsfeed_items = payload.get("newsfeed_items")
        if isinstance(newsfeed_items, list) and newsfeed_items:
            for wrap in newsfeed_items:
                if not isinstance(wrap, dict):
                    continue
                item = wrap.get("item") if isinstance(wrap.get("item"), dict) else wrap
                if isinstance(item, dict):
                    _take(item)
            if found:
                return found

    def _walk(node: Any, *, allow_posts: bool = True) -> None:
        if isinstance(node, dict):
            if allow_posts:
                for wrap_key in ("post", "wall", "wall_post", "item"):
                    nested = node.get(wrap_key)
                    if isinstance(nested, dict):
                        _take(nested)
                _take(node)
            for key, value in node.items():
                if not isinstance(value, (dict, list)):
                    continue
                # Skip nested media / originals that create false positives.
                if key in {"copy_history", "attachments", "attachments_meta", "photo", "sizes"}:
                    continue
                _walk(value, allow_posts=allow_posts)
        elif isinstance(node, list):
            for item in node:
                _walk(item, allow_posts=allow_posts)

    _walk(payload)
    return found


class VKCatalogPostMapper:
    """Map raw VK wall/catalog objects to domain CatalogPost."""

    def map(self, raw_post: Any) -> CatalogPost:
        if not isinstance(raw_post, dict):
            raise CatalogMapperError("raw post must be a dict")
        if not looks_like_wall_post(raw_post):
            raise CatalogMapperError("object is not a wall post")

        key = _post_key(raw_post)
        if key is None:
            raise CatalogMapperError("missing owner_id/id")
        owner_id, post_id = key

        text = str(raw_post.get("text") or "").strip()
        if not text:
            history = raw_post.get("copy_history")
            if isinstance(history, list) and history:
                first = history[0]
                if isinstance(first, dict):
                    text = str(first.get("text") or "").strip()

        try:
            ts = int(raw_post.get("date") or 0)
        except (TypeError, ValueError):
            ts = 0
        date = datetime.fromtimestamp(ts, tz=UTC) if ts > 0 else datetime.fromtimestamp(0, tz=UTC)

        links = extract_urls_from_post(raw_post)
        history = raw_post.get("copy_history")
        if isinstance(history, list):
            for item in history:
                if isinstance(item, dict):
                    for link in extract_urls_from_post(item):
                        if all(existing.url != link.url for existing in links):
                            links.append(PostLink(url=link.url, position=len(links)))

        return CatalogPost(
            source=SOURCE_VK_CATALOG,
            owner_id=owner_id,
            post_id=post_id,
            text=text,
            date=date,
            likes=_counter(raw_post, "likes"),
            comments=_counter(raw_post, "comments"),
            reposts=_counter(raw_post, "reposts"),
            views=_counter(raw_post, "views"),
            links=links,
        )

    def map_many(self, raw_posts: list[Any]) -> list[CatalogPost]:
        posts: list[CatalogPost] = []
        for raw in raw_posts:
            try:
                posts.append(self.map(raw))
            except CatalogMapperError:
                continue
        return posts

    def map_response(self, response: Any) -> list[CatalogPost]:
        return self.map_many(iter_raw_wall_posts(response))
