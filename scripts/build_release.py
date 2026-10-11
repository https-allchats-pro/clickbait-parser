#!/usr/bin/env python3
"""Build Clickbait Parser desktop apps for macOS and/or Windows.

PyInstaller cannot cross-compile: a macOS host produces macOS artifacts,
a Windows host produces Windows artifacts. Run this script on each OS
(or in CI) to get both builds.

Usage:
  python scripts/build_release.py              # current OS
  python scripts/build_release.py --os macos
  python scripts/build_release.py --os windows
  python scripts/build_release.py --os all     # host OS only + note for the other
  python scripts/build_release.py --clean
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "packaging" / "clickbait.spec"
DIST = ROOT / "dist"
BUILD = ROOT / "build"
APP_NAME = "ClickbaitParser"
RELEASE = DIST / "release"


def _host_os() -> str:
    system = platform.system().lower()
    if system == "darwin":
        return "macos"
    if system == "windows":
        return "windows"
    return system


def _ensure_pyinstaller(python: Path) -> None:
    try:
        subprocess.run(
            [str(python), "-c", "import PyInstaller"],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        print("→ installing pyinstaller…")
        subprocess.run(
            [str(python), "-m", "pip", "install", "pyinstaller>=6.3"],
            check=True,
        )


def _python() -> Path:
    venv = ROOT / ".venv"
    if sys.platform == "win32":
        candidate = venv / "Scripts" / "python.exe"
    else:
        candidate = venv / "bin" / "python"
    if candidate.is_file():
        return candidate
    return Path(sys.executable)


def _clean() -> None:
    for path in (BUILD, DIST / APP_NAME, DIST / f"{APP_NAME}.app", RELEASE):
        if path.exists():
            print(f"→ remove {path.relative_to(ROOT)}")
            shutil.rmtree(path, ignore_errors=True)
    # leftover onedir / zip artifacts from previous runs
    for pattern in (f"{APP_NAME}-macos*", f"{APP_NAME}-windows*"):
        for path in DIST.glob(pattern):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)


def _run_pyinstaller(python: Path) -> None:
    cmd = [
        str(python),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        str(SPEC),
    ]
    print("→", " ".join(cmd))
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.run(cmd, check=True, cwd=ROOT, env=env)


def _zip_dir(source: Path, zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(source.rglob("*")):
            if file_path.is_file():
                zf.write(file_path, file_path.relative_to(source.parent))
    print(f"→ wrote {zip_path.relative_to(ROOT)} ({zip_path.stat().st_size // 1_000_000} MB)")


def _package_macos() -> Path:
    app = DIST / f"{APP_NAME}.app"
    onedir = DIST / APP_NAME
    if not app.is_dir():
        # Fallback if BUNDLE step was skipped for some reason.
        if not onedir.is_dir():
            raise FileNotFoundError(f"macOS build missing: {app} or {onedir}")
        app = onedir
    RELEASE.mkdir(parents=True, exist_ok=True)
    arch = platform.machine().replace("arm64", "arm64").replace("x86_64", "x86_64")
    out = RELEASE / f"{APP_NAME}-macos-{arch}.zip"
    _zip_dir(app, out)
    return out


def _package_windows() -> Path:
    onedir = DIST / APP_NAME
    if not onedir.is_dir():
        raise FileNotFoundError(f"Windows build missing: {onedir}")
    RELEASE.mkdir(parents=True, exist_ok=True)
    out = RELEASE / f"{APP_NAME}-windows-x64.zip"
    _zip_dir(onedir, out)
    return out


def build_for_host(*, clean: bool) -> Path:
    host = _host_os()
    if host not in {"macos", "windows"}:
        raise SystemExit(
            f"Unsupported host OS '{host}'. Build on macOS or Windows."
        )
    python = _python()
    print(f"→ python: {python}")
    print(f"→ target: {host} (native)")
    _ensure_pyinstaller(python)
    if clean:
        _clean()
    _run_pyinstaller(python)
    if host == "macos":
        return _package_macos()
    return _package_windows()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--os",
        choices=("macos", "windows", "all", "current"),
        default="current",
        help="Which OS artifact to build (default: current host)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove previous build/dist artifacts before building",
    )
    args = parser.parse_args(argv)

    host = _host_os()
    wanted = host if args.os in {"current", "all"} else args.os

    if wanted != host:
        print(
            f"Cannot cross-compile {wanted} on {host}.\n"
            f"Run this script on a {wanted} machine (or in CI):\n"
            f"  python scripts/build_release.py --os {wanted} --clean",
            file=sys.stderr,
        )
        return 2

    artifact = build_for_host(clean=args.clean)
    print(f"✓ built {artifact}")

    if args.os == "all":
        other = "windows" if host == "macos" else "macos"
        print(
            f"\nNote: '{other}' artifact must be built on {other}:\n"
            f"  python scripts/build_release.py --os {other} --clean"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
