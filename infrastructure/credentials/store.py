from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol


class CredentialStore(Protocol):
    def save(self, provider: str, provider_user_id: int, credentials: dict[str, Any]) -> None: ...

    def load(self, provider: str, provider_user_id: int) -> dict[str, Any] | None: ...

    def delete(self, provider: str, provider_user_id: int) -> None: ...


class FileCredentialStore:
    """Persist provider session tokens as JSON files (never passwords)."""

    def __init__(self, root: Path | str | None = None) -> None:
        if root is None:
            root = Path.home() / ".clickbait-parser" / "credentials"
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self._root, 0o700)
        except OSError:
            pass

    def save(self, provider: str, provider_user_id: int, credentials: dict[str, Any]) -> None:
        path = self._path(provider, provider_user_id)
        payload = json.dumps(credentials, ensure_ascii=False, indent=2)
        path.write_text(payload, encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def load(self, provider: str, provider_user_id: int) -> dict[str, Any] | None:
        path = self._path(provider, provider_user_id)
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        return data

    def delete(self, provider: str, provider_user_id: int) -> None:
        path = self._path(provider, provider_user_id)
        if path.is_file():
            path.unlink()

    def _path(self, provider: str, provider_user_id: int) -> Path:
        safe_provider = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in provider)
        return self._root / f"{safe_provider}_{provider_user_id}.json"
