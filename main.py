#!/usr/bin/env python3
"""CLI entrypoint for clickbait-parser Phase 1 (VK auth & profiles)."""

from __future__ import annotations

import argparse
import logging
import sys

from app.auth.service import AuthService
from infrastructure.credentials.store import FileCredentialStore
from infrastructure.db.database import connect, init_schema
from infrastructure.db.repositories.profile_repository import ProfileRepository
from infrastructure.vk.client import VKClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clickbait-parser",
        description="VK clickbait analyzer — Phase 1: authentication & profiles",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    auth = sub.add_parser("auth", help="Authorize a messenger profile")
    auth.add_argument("provider", choices=["vk"], help="Messenger provider")
    auth.add_argument(
        "--method",
        default="qr",
        choices=["qr"],
        help="Auth method (default: qr)",
    )
    auth.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the local QR HTML page (still prints ASCII QR in terminal)",
    )

    sub.add_parser("profiles", help="List saved profiles")

    logout = sub.add_parser("logout", help="Remove a saved profile and its credentials")
    logout.add_argument("profile_id", type=int, help="Profile id from `profiles`")

    return parser


def _format_profile(profile) -> str:
    name = " ".join(part for part in (profile.first_name, profile.last_name) if part).strip()
    name = name or "(no name)"
    return (
        f"id={profile.id} provider={profile.provider} "
        f"user_id={profile.provider_user_id} name={name}"
    )


def _build_service(*, open_browser: bool = True) -> AuthService:
    conn = connect()
    init_schema(conn)
    return AuthService(
        vk_client=VKClient(
            open_browser=open_browser,
            on_status=lambda msg: print(msg, flush=True),
        ),
        profiles=ProfileRepository(conn),
        credentials=FileCredentialStore(),
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    # Avoid accidental credential leakage via library loggers.
    logging.getLogger("allchats_sdk").setLevel(logging.WARNING)

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "auth":
        if args.provider != "vk":
            parser.error(f"unsupported provider: {args.provider}")
        service = _build_service(open_browser=not args.no_browser)
        try:
            profile = service.login_vk(method=args.method)
        except Exception as exc:
            print(f"auth failed: {exc}", file=sys.stderr)
            return 1
        print(_format_profile(profile))
        return 0

    if args.command == "profiles":
        service = _build_service()
        profiles = service.get_profiles()
        if not profiles:
            print("(no profiles)")
            return 0
        for profile in profiles:
            print(_format_profile(profile))
        return 0

    if args.command == "logout":
        service = _build_service()
        profile = service.get_profile(args.profile_id)
        if profile is None:
            print(f"profile {args.profile_id} not found", file=sys.stderr)
            return 1
        service.logout(args.profile_id)
        print(f"logged out profile {args.profile_id}")
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
