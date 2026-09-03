from __future__ import annotations

import logging
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from allchats_sdk.credentials import new_vk_credentials
from allchats_sdk.providers.vk.native_api import get_user_info
from allchats_sdk.providers.vk.qr_auth import (
    POLL_INTERVAL_SEC,
    QrStatus,
    VkQrAuthError,
    check_auth_code,
    init_qr_session,
    resolve_approved_token,
)

from infrastructure.vk.qr_display import render_ascii_qr, write_qr_html_page

logger = logging.getLogger(__name__)

StatusCallback = Callable[[str], None]


@dataclass
class VKUser:
    user_id: int
    first_name: str | None
    last_name: str | None


class VKClient:
    """Thin VK auth facade. Hides qr_auth / native_api details from app layer."""

    def __init__(
        self,
        *,
        device_name: str = "Clickbait Parser",
        open_browser: bool = True,
        on_status: StatusCallback | None = None,
        on_qr: Callable[[str], None] | None = None,
        poll_interval: float = POLL_INTERVAL_SEC,
        timeout_sec: float = 300.0,
    ) -> None:
        self._device_name = device_name
        self._open_browser = open_browser
        self._on_status = on_status or (lambda _msg: None)
        self._on_qr = on_qr
        self._poll_interval = poll_interval
        self._timeout_sec = timeout_sec
        self._access_token: str | None = None
        self._user: VKUser | None = None
        self._auth_method: str = ""
        self._qr_html_path: Path | None = None

    def authenticate(self, *, method: str = "qr") -> VKUser:
        method = method.strip().lower()
        if method != "qr":
            raise ValueError(f"unsupported auth method: {method!r} (Phase 1 supports: qr)")
        return self._authenticate_qr()

    def get_current_user(self) -> VKUser:
        if self._user is None:
            raise RuntimeError("not authenticated")
        return self._user

    def get_credentials(self) -> dict[str, Any]:
        if self._access_token is None or self._user is None:
            raise RuntimeError("not authenticated")
        creds = new_vk_credentials(account_id=str(self._user.user_id))
        creds.update(
            {
                "user_id": str(self._user.user_id),
                "access_token": self._access_token,
                "auth_method": self._auth_method or "qr",
                "state_instance": "authorized",
            }
        )
        return creds

    def close(self) -> None:
        self._access_token = None
        self._user = None
        self._auth_method = ""

    def _authenticate_qr(self) -> VKUser:
        self._on_status("Starting VK QR session…")
        auth_url, auth_hash, anonym_token = init_qr_session(device_name=self._device_name)
        self._show_qr(auth_url)

        deadline = time.monotonic() + self._timeout_sec
        while time.monotonic() < deadline:
            time.sleep(self._poll_interval)
            result = check_auth_code(anonym_token, auth_hash)
            status = QrStatus(result["status"])
            self._on_status(f"QR status: {status.name.lower()}")

            if status in (QrStatus.CREATED, QrStatus.OPENED):
                continue

            if status == QrStatus.APPROVED:
                access_token, user_id = resolve_approved_token(
                    result,
                    anonym_token,
                    auth_hash,
                )
                self._access_token = access_token
                self._auth_method = "qr"
                self._user = self._load_user(access_token, fallback_user_id=user_id)
                self._on_status("authorized")
                return self._user

            if status == QrStatus.DECLINED:
                raise VkQrAuthError("Login declined in VK app")

            if status == QrStatus.EXPIRED:
                raise VkQrAuthError("QR code expired")

            raise VkQrAuthError(f"Unknown QR status: {status}")

        raise VkQrAuthError("QR auth timed out")

    def _show_qr(self, auth_url: str) -> None:
        # Do NOT open auth_url in a browser — qr.vk.ru hits anti-bot / redirects.
        # Encode the URL as a QR image and let the user scan it in the VK app
        # (same approach as the AllChats frontend).
        if self._on_qr is not None:
            self._on_qr(auth_url)
            self._on_status("Отсканируйте QR-код в приложении VK")
            if not self._open_browser:
                return

        ascii_qr = render_ascii_qr(auth_url)
        if ascii_qr:
            self._on_status(ascii_qr)

        html_path = write_qr_html_page(auth_url)
        self._qr_html_path = html_path
        self._on_status(
            "Scan the QR with the VK mobile app (Camera / QR scanner).\n"
            f"HTML page: {html_path}\n"
            f"(raw url for debugging only — do not open in desktop browser):\n{auth_url}"
        )
        if self._open_browser:
            try:
                webbrowser.open(html_path.as_uri())
            except Exception:
                logger.debug("failed to open local QR HTML page", exc_info=True)

    def _load_user(self, access_token: str, *, fallback_user_id: int | None) -> VKUser:
        info = get_user_info(access_token=access_token)
        user_id = int(info.get("id") or fallback_user_id or 0)
        if not user_id:
            raise VkQrAuthError("failed to resolve VK user id")
        first = str(info.get("first_name") or "").strip() or None
        last = str(info.get("last_name") or "").strip() or None
        return VKUser(user_id=user_id, first_name=first, last_name=last)
