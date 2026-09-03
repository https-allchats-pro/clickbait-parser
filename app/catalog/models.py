from __future__ import annotations

# Re-export domain models for the catalog application package.
from domain.posts import (  # noqa: F401
    SOURCE_VK_CATALOG,
    CatalogPage,
    CatalogPost,
    CollectResult,
    PostLink,
    UpsertResult,
)
