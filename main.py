#!/usr/bin/env python3
"""CLI entrypoint for clickbait-parser (auth, catalog, analysis)."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

from allchats_sdk.credentials import vk_authorized

from analysis.analyzer import RuleBasedClickbaitAnalyzer
from app.analysis.service import AnalysisService
from app.auth.service import AuthService
from app.catalog.service import CatalogService
from infrastructure.credentials.store import FileCredentialStore
from infrastructure.db.database import connect, init_schema
from infrastructure.db.repositories.analysis_repository import AnalysisRepository
from infrastructure.db.repositories.post_repository import PostRepository
from infrastructure.db.repositories.profile_repository import ProfileRepository
from infrastructure.vk.catalog_client import CatalogAuthError, CatalogError, VKCatalogClient
from infrastructure.vk.client import VKClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clickbait-parser",
        description="VK clickbait analyzer — auth, catalog collector, rule-based analysis",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    auth = sub.add_parser("auth", help="Authorize a messenger profile")
    auth.add_argument("provider", choices=["vk"], help="Messenger provider")
    auth.add_argument("--method", default="qr", choices=["qr"], help="Auth method")
    auth.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the local QR HTML page",
    )

    sub.add_parser("profiles", help="List saved profiles")

    logout = sub.add_parser("logout", help="Remove a saved profile and its credentials")
    logout.add_argument("profile_id", type=int, help="Profile id from `profiles`")

    catalog = sub.add_parser("catalog", help="Global VK catalog operations")
    catalog_sub = catalog.add_subparsers(dest="catalog_command", required=True)
    collect = catalog_sub.add_parser("collect", help="Fetch catalog statuses into SQLite")
    collect.add_argument("--count", type=int, default=100, help="Max posts to fetch")
    collect.add_argument("--pages", type=int, default=10, help="Max catalog pages")
    collect.add_argument("--page-size", type=int, default=100, help="Posts per VK page")
    collect.add_argument(
        "-q",
        "--query",
        default="",
        help="Search query for catalog.getSearchStatuses (empty = global/top statuses)",
    )
    collect.add_argument(
        "--profile-id",
        type=int,
        default=None,
        help="VK profile id (default: first saved vk profile)",
    )
    collect.add_argument(
        "--start-from",
        default=None,
        help="Optional pagination cursor from a previous collect",
    )

    posts = sub.add_parser("posts", help="Show latest saved catalog posts")
    posts.add_argument("--limit", type=int, default=20, help="Max posts to print")

    analysis = sub.add_parser("analysis", help="Rule-based clickbait analysis")
    analysis_sub = analysis.add_subparsers(dest="analysis_command", required=True)
    run = analysis_sub.add_parser("run", help="Analyze latest saved posts")
    run.add_argument("--limit", type=int, default=100, help="Max posts to analyze")
    run.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Clickbait score threshold (0..1)",
    )
    run.add_argument(
        "--post-id",
        type=int,
        default=None,
        help="Analyze a single local posts.id",
    )

    alist = analysis_sub.add_parser("list", help="Show latest analysis results")
    alist.add_argument("--limit", type=int, default=20)

    aclick = analysis_sub.add_parser("clickbait", help="Show posts marked as clickbait")
    aclick.add_argument("--limit", type=int, default=20)

    return parser


def _format_profile(profile) -> str:
    name = " ".join(part for part in (profile.first_name, profile.last_name) if part).strip()
    name = name or "(no name)"
    return (
        f"id={profile.id} provider={profile.provider} "
        f"user_id={profile.provider_user_id} name={name}"
    )


def _truncate(text: str, limit: int = 160) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _format_post(post) -> str:
    when = post.date.astimezone().strftime("%Y-%m-%d %H:%M") if isinstance(post.date, datetime) else "?"
    label = "VK" if post.source.startswith("vk") else post.source.upper()
    body = _truncate(post.text) or "(no text)"
    return (
        f"[{label}] owner={post.owner_id} post={post.post_id}\n"
        f"{when}\n"
        f"{body}\n"
        f"Links: {len(post.links)}"
    )


def _format_analysis(post, analysis) -> str:
    label = "CLICKBAIT" if analysis.is_clickbait else "NORMAL"
    reasons = ", ".join(analysis.reasons) if analysis.reasons else "(none)"
    return (
        f"{analysis.score:0.2f}  {label:<9}  owner={post.owner_id}  post={post.post_id}\n"
        f"Причины: {reasons}"
    )


def _open_db():
    conn = connect()
    init_schema(conn)
    return conn


def _build_auth_service(*, open_browser: bool = True) -> AuthService:
    conn = _open_db()
    return AuthService(
        vk_client=VKClient(
            open_browser=open_browser,
            on_status=lambda msg: print(msg, flush=True),
        ),
        profiles=ProfileRepository(conn),
        credentials=FileCredentialStore(),
    )


def _build_analysis_service(*, threshold: float = 0.5) -> AnalysisService:
    conn = _open_db()
    return AnalysisService(
        posts=PostRepository(conn),
        analyses=AnalysisRepository(conn),
        analyzer=RuleBasedClickbaitAnalyzer(threshold=threshold),
    )


def _resolve_vk_token(*, profile_id: int | None) -> tuple[int, str]:
    conn = _open_db()
    profiles = ProfileRepository(conn)
    creds_store = FileCredentialStore()

    if profile_id is not None:
        profile = profiles.get(profile_id)
        if profile is None:
            raise CatalogAuthError(f"profile {profile_id} not found")
        if profile.provider != "vk":
            raise CatalogAuthError(f"profile {profile_id} is not a vk profile")
    else:
        vk_profiles = [p for p in profiles.get_all() if p.provider == "vk"]
        if not vk_profiles:
            raise CatalogAuthError("no vk profiles — run: python main.py auth vk --method qr")
        profile = vk_profiles[0]
        assert profile.id is not None

    credentials = creds_store.load(profile.provider, profile.provider_user_id)
    if not credentials or not vk_authorized(credentials):
        raise CatalogAuthError(
            f"vk credentials missing for profile {profile.id} — re-run auth"
        )
    token = str(credentials.get("access_token") or "").strip()
    if not token:
        raise CatalogAuthError("vk access_token is empty — re-run auth")
    assert profile.id is not None
    return profile.id, token


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("allchats_sdk").setLevel(logging.WARNING)

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "auth":
        service = _build_auth_service(open_browser=not args.no_browser)
        try:
            profile = service.login_vk(method=args.method)
        except Exception as exc:
            print(f"auth failed: {exc}", file=sys.stderr)
            return 1
        print(_format_profile(profile))
        return 0

    if args.command == "profiles":
        service = _build_auth_service()
        profiles = service.get_profiles()
        if not profiles:
            print("(no profiles)")
            return 0
        for profile in profiles:
            print(_format_profile(profile))
        return 0

    if args.command == "logout":
        service = _build_auth_service()
        profile = service.get_profile(args.profile_id)
        if profile is None:
            print(f"profile {args.profile_id} not found", file=sys.stderr)
            return 1
        service.logout(args.profile_id)
        print(f"logged out profile {args.profile_id}")
        return 0

    if args.command == "catalog":
        if args.catalog_command == "collect":
            try:
                profile_id, token = _resolve_vk_token(profile_id=args.profile_id)
                conn = _open_db()
                service = CatalogService(
                    client=VKCatalogClient(access_token=token),
                    posts=PostRepository(conn),
                )
                result = service.collect(
                    count=args.count,
                    start_from=args.start_from,
                    pages=args.pages,
                    page_size=args.page_size,
                    query=args.query,
                )
            except CatalogAuthError as exc:
                print(f"auth error: {exc}", file=sys.stderr)
                return 1
            except CatalogError as exc:
                print(f"catalog error: {exc}", file=sys.stderr)
                return 1

            print("VK Global Catalog")
            print(f"Profile:    {profile_id}")
            print(f"Method:     catalog.getSearchStatuses")
            if args.query:
                print(f"Query:      {args.query}")
            print(f"Fetched:    {result.fetched}")
            print(f"Inserted:   {result.upsert.inserted}")
            print(f"Updated:    {result.upsert.updated}")
            print(f"Unchanged:  {result.upsert.unchanged}")
            print(f"Pages:      {result.pages}")
            if result.next_from:
                print(f"next_from:  {result.next_from}")
            if result.fetched == 0:
                print(
                    "Hint: catalog.getSearchTop returns people/groups only; "
                    "this CLI uses catalog.getSearchStatuses for posts. "
                    "Try: --query 'новости'",
                    file=sys.stderr,
                )
            return 0
        parser.error(f"unknown catalog command: {args.catalog_command}")
        return 2

    if args.command == "posts":
        conn = _open_db()
        latest = PostRepository(conn).get_latest(limit=args.limit)
        if not latest:
            print("(no posts)")
            return 0
        for index, post in enumerate(latest):
            if index:
                print()
            print(_format_post(post))
        return 0

    if args.command == "analysis":
        if args.analysis_command == "run":
            threshold = float(args.threshold)
            if not 0.0 <= threshold <= 1.0:
                parser.error("--threshold must be between 0 and 1")
            service = _build_analysis_service(threshold=threshold)
            try:
                if args.post_id is not None:
                    analysis = service.analyze_post(args.post_id)
                    rows = service.list_latest(limit=1000)
                    match = next((pair for pair in rows if pair[1].post_id == args.post_id), None)
                    if match is None:
                        # Fallback: load post directly for display
                        conn = _open_db()
                        post = PostRepository(conn).get_by_id(args.post_id)
                        if post is None:
                            print(f"post {args.post_id} not found", file=sys.stderr)
                            return 1
                        print(_format_analysis(post, analysis))
                    else:
                        print(_format_analysis(match[0], analysis))
                    return 0
                result = service.analyze_posts(limit=args.limit)
            except ValueError as exc:
                print(f"analysis error: {exc}", file=sys.stderr)
                return 1
            print("Clickbait Analysis")
            print(f"Analyzed:   {result.analyzed}")
            print(f"Clickbait:  {result.clickbait}")
            print(f"Normal:     {result.normal}")
            print(f"Skipped:    {result.skipped}")
            print(f"Threshold:  {threshold}")
            return 0

        if args.analysis_command == "list":
            service = _build_analysis_service()
            rows = service.list_latest(limit=args.limit)
            if not rows:
                print("(no analysis results)")
                return 0
            for index, (post, analysis) in enumerate(rows):
                if index:
                    print()
                print(_format_analysis(post, analysis))
            return 0

        if args.analysis_command == "clickbait":
            service = _build_analysis_service()
            rows = service.list_clickbait(limit=args.limit)
            if not rows:
                print("(no clickbait posts)")
                return 0
            for index, (post, analysis) in enumerate(rows):
                if index:
                    print()
                print(_format_analysis(post, analysis))
            return 0

        parser.error(f"unknown analysis command: {args.analysis_command}")
        return 2

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
