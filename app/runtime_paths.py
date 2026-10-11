from __future__ import annotations

import shutil
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    """Read-only resources shipped inside the PyInstaller bundle."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parents[1]


def project_root() -> Path:
    """Writable project / install root (dev tree or folder next to the exe)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def user_data_root() -> Path:
    """Writable per-user data (credentials, sqlite, trained models)."""
    if is_frozen():
        root = Path.home() / ".clickbait-parser"
        root.mkdir(parents=True, exist_ok=True)
        return root
    return project_root()


def default_models_dir() -> Path:
    """Writable ``models/``; seeds from the bundle on first frozen launch."""
    if is_frozen():
        user = user_data_root() / "models"
        user.mkdir(parents=True, exist_ok=True)
        bundled = bundle_root() / "models"
        for name in ("clickbait_model.joblib", "clickbait_model.meta.json"):
            src = bundled / name
            dst = user / name
            if src.is_file() and not dst.is_file():
                shutil.copy2(src, dst)
        return user
    path = project_root() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_db_path() -> Path:
    """Prefer project-local data/app.sqlite3; fall back to ~/.clickbait-parser."""
    if is_frozen():
        return user_data_root() / "app.sqlite3"
    local = project_root() / "data" / "app.sqlite3"
    if local.parent.is_dir():
        return local
    root = Path.home() / ".clickbait-parser"
    root.mkdir(parents=True, exist_ok=True)
    return root / "app.sqlite3"


def default_dataset_csv() -> Path:
    if is_frozen():
        bundled = bundle_root() / "dataset" / "clickbait_dataset.csv"
        if bundled.is_file():
            return bundled
        return user_data_root() / "dataset" / "clickbait_dataset.csv"
    return project_root() / "dataset" / "clickbait_dataset.csv"
