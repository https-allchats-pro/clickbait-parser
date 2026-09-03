from __future__ import annotations

from typing import Protocol

from allchats_sdk.providers.vk.catalog import get_newsfeed_search
from allchats_sdk.providers.vk.native_api import VkNativeApiError

from domain.posts import CatalogPage
from infrastructure.vk.catalog_mapper import VKCatalogPostMapper


class CatalogError(RuntimeError):
    """Application-level catalog failure (no credentials in message)."""


class CatalogAuthError(CatalogError):
    pass


class CatalogRateLimitError(CatalogError):
    pass


class CatalogClient(Protocol):
    def get_search_top(
        self,
        *,
        count: int = 100,
        start_from: str | None = None,
        query: str | None = None,
    ) -> CatalogPage: ...


class VKCatalogClient:
    """Infrastructure adapter: VK wall-post search → domain CatalogPage.

    Uses ``newsfeed.search`` (real pagination via ``next_from``).
    ``catalog.getSearchStatuses`` only returns ~15–20 unique UI posts and does
    not advance the cursor usefully, so it is not used for collection anymore.
    """

    def __init__(
        self,
        *,
        access_token: str,
        mapper: VKCatalogPostMapper | None = None,
    ) -> None:
        token = (access_token or "").strip()
        if not token:
            raise CatalogAuthError("VK access token is required")
        self._access_token = token
        self._mapper = mapper or VKCatalogPostMapper()

    def get_search_top(
        self,
        *,
        count: int = 100,
        start_from: str | None = None,
        query: str | None = None,
    ) -> CatalogPage:
        try:
            page = get_newsfeed_search(
                access_token=self._access_token,
                count=count,
                start_from=start_from,
                q=query,
            )
        except VkNativeApiError as exc:
            if exc.error_code in {5, 1117}:
                raise CatalogAuthError("VK session expired or unauthorized") from exc
            if exc.is_rate_limit:
                raise CatalogRateLimitError("VK rate limit exceeded") from exc
            raise CatalogError(f"VK catalog error: {exc}") from exc
        except OSError as exc:
            raise CatalogError(f"network error while calling VK catalog: {exc}") from exc

        posts = self._mapper.map_response(page.response)
        return CatalogPage(posts=posts, next_from=page.next_from)
