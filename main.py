#!/usr/bin/env python3
"""CLI entrypoint for clickbait-parser (auth, catalog, analysis, dataset, pipeline, gui)."""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from allchats_sdk.credentials import vk_authorized

from analysis.analyzer import RuleBasedClickbaitAnalyzer
from app.analysis.service import AnalysisService
from app.auth.service import AuthService
from app.catalog.service import CatalogService
from app.composition import create_clickbait_pipeline
from app.dataset.service import DatasetService
from app.pipeline.service import ClickbaitPipeline
from domain.dataset import DatasetLabel
from domain.pipeline import PipelineProgress, PipelineRequest, PipelineState
from infrastructure.credentials.store import FileCredentialStore
from infrastructure.db.database import connect, init_schema
from infrastructure.db.repositories.analysis_repository import AnalysisRepository
from infrastructure.db.repositories.label_repository import LabelRepository
from infrastructure.db.repositories.post_repository import PostRepository
from infrastructure.db.repositories.profile_repository import ProfileRepository
from infrastructure.vk.catalog_client import CatalogAuthError, CatalogError, VKCatalogClient
from infrastructure.vk.client import VKClient

DEFAULT_DATASET_CSV = Path(__file__).resolve().parent / "dataset" / "clickbait_dataset.csv"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clickbait-parser",
        description="VK clickbait analyzer — auth, catalog, analysis, dataset, pipeline, gui",
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
        help="Search query for catalog.getSearchStatuses",
    )
    collect.add_argument("--profile-id", type=int, default=None)
    collect.add_argument("--start-from", default=None)

    posts = sub.add_parser("posts", help="Show latest saved catalog posts")
    posts.add_argument("--limit", type=int, default=20)

    analysis = sub.add_parser("analysis", help="Rule-based clickbait analysis")
    analysis_sub = analysis.add_subparsers(dest="analysis_command", required=True)
    run = analysis_sub.add_parser("run", help="Analyze latest saved posts")
    run.add_argument("--limit", type=int, default=100)
    run.add_argument("--threshold", type=float, default=0.5)
    run.add_argument("--post-id", type=int, default=None)
    alist = analysis_sub.add_parser("list", help="Show latest analysis results")
    alist.add_argument("--limit", type=int, default=20)
    aclick = analysis_sub.add_parser("clickbait", help="Show posts marked as clickbait")
    aclick.add_argument("--limit", type=int, default=20)

    dataset = sub.add_parser("dataset", help="Manual labeling & dataset export")
    dataset_sub = dataset.add_subparsers(dest="dataset_command", required=True)
    label = dataset_sub.add_parser("label", help="Interactive human labeling")
    label.add_argument(
        "--mode",
        choices=["default", "random", "suspicious"],
        default="default",
        help="Unlabeled post sampling strategy",
    )
    label.add_argument(
        "--max",
        type=int,
        default=0,
        help="Stop after N labels this session (0 = unlimited)",
    )
    dataset_sub.add_parser("stats", help="Show labeling / disagreement stats")
    export = dataset_sub.add_parser("export", help="Export labeled dataset to CSV")
    export.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_DATASET_CSV,
        help=f"CSV path (default: {DEFAULT_DATASET_CSV})",
    )
    dataset_sub.add_parser("validate", help="Soft quality checks before ML")

    pipeline = sub.add_parser("pipeline", help="Collect + analyze orchestration")
    pipeline_sub = pipeline.add_subparsers(dest="pipeline_command", required=True)
    prun = pipeline_sub.add_parser("run", help="Run collect → analyze pipeline")
    prun.add_argument("--limit", type=int, required=True, help="Max posts to process")
    prun.add_argument(
        "-q",
        "--query",
        default=None,
        help="Optional catalog search query",
    )
    prun.add_argument("--profile-id", type=int, default=None)
    prun.add_argument("--threshold", type=float, default=0.5)
    prun.add_argument("--page-size", type=int, default=100)

    gui = sub.add_parser("gui", help="Open PyQt6 desktop MVP")
    gui.add_argument("--profile-id", type=int, default=None)
    gui.add_argument("--threshold", type=float, default=0.5)
    gui.add_argument("--page-size", type=int, default=100)

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


def _format_pipeline_analysis(post, analysis) -> str:
    label = "CLICKBAIT" if analysis.is_clickbait else "NORMAL"
    reasons = ", ".join(analysis.reasons) if analysis.reasons else "(none)"
    return (
        f"{analysis.score:0.2f} {label}\n"
        f"owner={post.owner_id} post={post.post_id}\n"
        f"Причины: {reasons}"
    )


class _PipelineCliProgress:
    """Prints pipeline progress without coupling application layer to CLI."""

    def __init__(self) -> None:
        self._last_state: PipelineState | None = None

    def __call__(self, progress: PipelineProgress) -> None:
        if progress.state == PipelineState.COLLECTING:
            if self._last_state != PipelineState.COLLECTING:
                print(f"State: {progress.state.value}")
            if progress.current > 0 or progress.total == 0:
                print(f"Collected: {progress.current}", flush=True)
            self._last_state = progress.state
            return
        if progress.state == PipelineState.ANALYZING:
            if self._last_state != PipelineState.ANALYZING:
                print()
                print(f"State: {progress.state.value}")
            if progress.total >= 0 and progress.current > 0:
                print(f"Analyzed: {progress.current}/{progress.total}", flush=True)
            self._last_state = progress.state
            return
        if progress.state == PipelineState.COMPLETED:
            print()
            print(f"State: {progress.state.value}")
            self._last_state = progress.state
            return
        if progress.state == PipelineState.FAILED:
            print()
            print(f"State: {progress.state.value}", file=sys.stderr)
            self._last_state = progress.state


def _print_label_card(post, analysis) -> None:
    when = post.date.astimezone().strftime("%Y-%m-%d %H:%M:%S") if isinstance(post.date, datetime) else "?"
    print("=" * 40)
    print(f"POST #{post.id}")
    print("=" * 40)
    print()
    print(f"Owner: {post.owner_id}")
    print(f"Date: {when}")
    print()
    print("Text:")
    print("-" * 40)
    print(post.text or "(empty)")
    print("-" * 40)
    print()
    print("Rule-based prediction:")
    if analysis is None:
        print("score: (no analysis yet — run `analysis run`)")
        print("is_clickbait: ?")
        print()
        print("Reasons:")
        print("- (none)")
        print()
        print("Features:")
        print("- (none)")
    else:
        print(f"score: {analysis.score:0.2f}")
        print(f"is_clickbait: {'YES' if analysis.is_clickbait else 'NO'}")
        print()
        print("Reasons:")
        if analysis.reasons:
            for reason in analysis.reasons:
                print(f"- {reason}")
        else:
            print("- (none)")
        print()
        print("Features:")
        for key, value in asdict(analysis.features).items():
            print(f"- {key}: {str(value).lower()}")
    print()
    print("Label:")
    print()
    print("[c] clickbait")
    print("[n] normal")
    print("[b] borderline")
    print("[s] skip")
    print("[q] quit")


def _open_db():
    conn = connect()
    init_schema(conn)
    return conn


def _build_auth_service(
    *,
    open_browser: bool = True,
    on_status=None,
    on_qr=None,
) -> AuthService:
    conn = _open_db()
    status_cb = on_status if on_status is not None else (lambda msg: print(msg, flush=True))
    return AuthService(
        vk_client=VKClient(
            open_browser=open_browser,
            on_status=status_cb,
            on_qr=on_qr,
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


def _build_dataset_service() -> DatasetService:
    conn = _open_db()
    return DatasetService(
        posts=PostRepository(conn),
        labels=LabelRepository(conn),
        analyses=AnalysisRepository(conn),
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


def _run_labeling_session(*, mode: str, max_labels: int) -> int:
    service = _build_dataset_service()
    labeled_now = 0
    skipped: set[int] = set()

    while True:
        if max_labels > 0 and labeled_now >= max_labels:
            print(f"Reached --max={max_labels}")
            return 0

        post = None
        for attempt in range(80):
            sample_mode = mode
            if attempt > 0 and mode == "default":
                sample_mode = "random"
            candidate = service.get_next_unlabeled_post(mode=sample_mode)  # type: ignore[arg-type]
            if candidate is None or candidate.id is None:
                break
            if candidate.id in skipped:
                continue
            post = candidate
            break

        if post is None or post.id is None:
            print("(no unlabeled posts left)")
            return 0

        _, analysis, _existing = service.get_label_context(post)
        _print_label_card(post, analysis)
        while True:
            choice = input("> ").strip().lower()
            if choice in {"q", "quit"}:
                return 0
            if choice in {"s", "skip"}:
                skipped.add(post.id)
                print("skipped")
                break
            mapping = {
                "c": DatasetLabel.CLICKBAIT,
                "clickbait": DatasetLabel.CLICKBAIT,
                "n": DatasetLabel.NORMAL,
                "normal": DatasetLabel.NORMAL,
                "b": DatasetLabel.BORDERLINE,
                "borderline": DatasetLabel.BORDERLINE,
            }
            if choice in mapping:
                saved = service.label_post(post.id, mapping[choice])
                print(f"saved label={saved.label.value} post_id={saved.post_id}")
                labeled_now += 1
                break
            print("use: c / n / b / s / q")
    return 0


def _run_gui(*, profile_id: int | None, threshold: float, page_size: int) -> int:
    from PyQt6.QtWidgets import QApplication, QDialog

    from app.gui.controller import PipelineController
    from ui.main_window import MainWindow
    from ui.profile_dialog import ProfileSelectDialog, format_profile_label

    app = QApplication(sys.argv)

    # AuthService for list/delete on the GUI thread (own SQLite connection).
    auth_service = _build_auth_service(open_browser=False)

    def auth_factory(*, on_status=None, on_qr=None):
        # Fresh AuthService/SQLite on the auth worker thread; QR stays in-app.
        return _build_auth_service(
            open_browser=False,
            on_status=on_status,
            on_qr=on_qr,
        )

    dialog = ProfileSelectDialog(
        profiles=auth_service,
        auth_factory=auth_factory,
        initial_profile_id=profile_id,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return 0

    selected_id = dialog.selected_profile_id
    if selected_id is None:
        print("no profile selected", file=sys.stderr)
        return 1

    try:
        resolved_id, token = _resolve_vk_token(profile_id=selected_id)
    except CatalogAuthError as exc:
        print(f"auth error: {exc}", file=sys.stderr)
        return 1

    profile = auth_service.get_profile(resolved_id)
    title_suffix = format_profile_label(profile) if profile is not None else f"#{resolved_id}"

    def pipeline_factory():
        # Must run on the worker thread so SQLite is not shared with the GUI thread.
        return create_clickbait_pipeline(
            access_token=token,
            threshold=threshold,
            page_size=page_size,
        )

    window = MainWindow()
    window.setWindowTitle(f"clickbait-parser — {title_suffix}")
    window.set_controller(
        PipelineController(window=window, pipeline_factory=pipeline_factory)
    )
    window.show()
    return int(app.exec())


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
                    conn = _open_db()
                    post = PostRepository(conn).get_by_id(args.post_id)
                    if post is None:
                        print(f"post {args.post_id} not found", file=sys.stderr)
                        return 1
                    print(_format_analysis(post, analysis))
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

    if args.command == "dataset":
        if args.dataset_command == "label":
            return _run_labeling_session(mode=args.mode, max_labels=args.max)

        if args.dataset_command == "stats":
            stats = _build_dataset_service().get_dataset_stats()
            print("Dataset statistics")
            print("------------------")
            print()
            print(f"Total labeled: {stats.total_labeled}")
            print()
            print(f"CLICKBAIT:   {stats.by_label[DatasetLabel.CLICKBAIT]}")
            print(f"NORMAL:      {stats.by_label[DatasetLabel.NORMAL]}")
            print(f"BORDERLINE:  {stats.by_label[DatasetLabel.BORDERLINE]}")
            print()
            print(f"Unlabeled:   {stats.unlabeled}")
            print()
            print("Rule prediction:")
            print(f"CLICKBAIT:   {stats.rule_clickbait}")
            print(f"NORMAL:      {stats.rule_normal}")
            print()
            print("Human vs Rule disagreement:")
            print()
            print(
                f"Human CLICKBAIT + Rule NORMAL: "
                f"{stats.disagreement_human_clickbait_rule_normal}"
            )
            print(
                f"Human NORMAL + Rule CLICKBAIT: "
                f"{stats.disagreement_human_normal_rule_clickbait}"
            )
            return 0

        if args.dataset_command == "export":
            path = _build_dataset_service().export_csv(args.output)
            print(f"exported: {path}")
            return 0

        if args.dataset_command == "validate":
            result = _build_dataset_service().validate()
            print("Dataset validation")
            print("------------------")
            print()
            print(f"Total labeled: {result.total_labeled}")
            print()
            print(f"CLICKBAIT: {result.by_label[DatasetLabel.CLICKBAIT]}")
            print(f"NORMAL: {result.by_label[DatasetLabel.NORMAL]}")
            print(f"BORDERLINE: {result.by_label[DatasetLabel.BORDERLINE]}")
            print()
            if result.warnings:
                for warning in result.warnings:
                    print(f"WARNING:\n{warning}")
                    print()
            else:
                print("OK: no soft warnings.")
            return 0

        parser.error(f"unknown dataset command: {args.dataset_command}")
        return 2

    if args.command == "pipeline":
        if args.pipeline_command == "run":
            threshold = float(args.threshold)
            if not 0.0 <= threshold <= 1.0:
                parser.error("--threshold must be between 0 and 1")
            if args.limit <= 0:
                parser.error("--limit must be > 0")

            print("Pipeline")
            print("────────")
            print()

            progress = _PipelineCliProgress()
            try:
                profile_id, token = _resolve_vk_token(profile_id=args.profile_id)
                conn = _open_db()
                catalog = CatalogService(
                    client=VKCatalogClient(access_token=token),
                    posts=PostRepository(conn),
                )
                pipeline = ClickbaitPipeline(
                    catalog_service=catalog,
                    analyzer=RuleBasedClickbaitAnalyzer(threshold=threshold),
                    analysis_repository=AnalysisRepository(conn),
                    on_progress=progress,
                    page_size=args.page_size,
                )
                request = PipelineRequest(limit=args.limit, query=args.query)
                result = pipeline.run(request)
            except CatalogAuthError as exc:
                print(f"auth error: {exc}", file=sys.stderr)
                return 1
            except CatalogError as exc:
                print(f"catalog error: {exc}", file=sys.stderr)
                return 1
            except ValueError as exc:
                print(f"pipeline error: {exc}", file=sys.stderr)
                return 1
            except Exception as exc:
                print(f"pipeline failed: {exc}", file=sys.stderr)
                return 1

            print()
            print("Results:")
            print("────────────────────────────────────────")
            print()
            if not result.posts:
                print("(no posts)")
            else:
                for index, item in enumerate(result.posts):
                    if index:
                        print()
                    print(_format_pipeline_analysis(item.post, item.analysis))
            return 0

        parser.error(f"unknown pipeline command: {args.pipeline_command}")
        return 2

    if args.command == "gui":
        threshold = float(args.threshold)
        if not 0.0 <= threshold <= 1.0:
            parser.error("--threshold must be between 0 and 1")
        return _run_gui(
            profile_id=args.profile_id,
            threshold=threshold,
            page_size=args.page_size,
        )

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
