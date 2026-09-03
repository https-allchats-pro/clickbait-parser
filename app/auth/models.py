from __future__ import annotations

from dataclasses import dataclass


@dataclass
class VKProfile:
    """Provider-agnostic profile metadata (no credentials, no SQL types)."""

    provider: str
    provider_user_id: int
    first_name: str | None = None
    last_name: str | None = None
    id: int | None = None
