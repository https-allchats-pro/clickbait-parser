from __future__ import annotations

from typing import Any, Protocol

from app.auth.models import VKProfile


class VKClientProtocol(Protocol):
    def authenticate(self, *, method: str = "qr") -> Any: ...

    def get_current_user(self) -> Any: ...

    def get_credentials(self) -> dict[str, Any]: ...

    def close(self) -> None: ...


class CredentialStoreProtocol(Protocol):
    def save(self, provider: str, provider_user_id: int, credentials: dict[str, Any]) -> None: ...

    def load(self, provider: str, provider_user_id: int) -> dict[str, Any] | None: ...

    def delete(self, provider: str, provider_user_id: int) -> None: ...


class ProfileRepositoryProtocol(Protocol):
    def create_or_update(self, profile: VKProfile) -> int: ...

    def get(self, profile_id: int) -> VKProfile | None: ...

    def get_all(self) -> list[VKProfile]: ...

    def delete(self, profile_id: int) -> None: ...


class AuthService:
    """Application auth orchestration. Does not import vk_api."""

    def __init__(
        self,
        *,
        vk_client: VKClientProtocol,
        profiles: ProfileRepositoryProtocol,
        credentials: CredentialStoreProtocol,
    ) -> None:
        self._vk = vk_client
        self._profiles = profiles
        self._credentials = credentials

    def login_vk(self, *, method: str = "qr") -> VKProfile:
        user = self._vk.authenticate(method=method)
        profile = VKProfile(
            provider="vk",
            provider_user_id=int(user.user_id),
            first_name=user.first_name,
            last_name=user.last_name,
        )
        profile_id = self._profiles.create_or_update(profile)
        creds = self._vk.get_credentials()
        self._credentials.save(profile.provider, profile.provider_user_id, creds)
        self._vk.close()
        saved = self._profiles.get(profile_id)
        if saved is None:
            profile.id = profile_id
            return profile
        return saved

    def get_profiles(self) -> list[VKProfile]:
        return self._profiles.get_all()

    def get_profile(self, profile_id: int) -> VKProfile | None:
        return self._profiles.get(profile_id)

    def logout(self, profile_id: int) -> None:
        profile = self._profiles.get(profile_id)
        if profile is None:
            return
        self._credentials.delete(profile.provider, profile.provider_user_id)
        self._profiles.delete(profile_id)
