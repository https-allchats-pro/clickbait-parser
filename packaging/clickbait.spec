# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for clickbait-parser GUI (macOS / Windows)."""

from __future__ import annotations

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
APP_NAME = "ClickbaitParser"
ENTRY = str(ROOT / "gui_entry.py")

datas: list[tuple[str, str]] = []
binaries: list[tuple[str, str]] = []
hiddenimports: list[str] = [
    "PyQt6",
    "sklearn",
    "sklearn.utils._cython_blas",
    "sklearn.neighbors._partition_nodes",
    "joblib",
    "qrcode",
    "PIL",
    "allchats_sdk",
    "allchats_sdk.providers.vk",
    "allchats_sdk.providers.vk.catalog",
    "allchats_sdk.providers.vk.native_api",
    "allchats_sdk.providers.vk.qr_auth",
    "allchats_sdk.credentials",
    "velopack",
]

for pkg in ("PyQt6", "sklearn", "allchats_sdk", "certifi"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

hiddenimports += collect_submodules("analysis")
hiddenimports += collect_submodules("app")
hiddenimports += collect_submodules("domain")
hiddenimports += collect_submodules("infrastructure")
hiddenimports += collect_submodules("ui")

models_dir = ROOT / "models"
if models_dir.is_dir():
    for path in models_dir.iterdir():
        if path.is_file() and path.name != ".gitkeep":
            datas.append((str(path), "models"))

dataset_dir = ROOT / "dataset"
if dataset_dir.is_dir():
    for path in dataset_dir.iterdir():
        if path.is_file() and path.suffix == ".csv":
            datas.append((str(path), "dataset"))

block_cipher = None

a = Analysis(
    [ENTRY],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # windowed GUI
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

# macOS .app bundle (ignored on Windows builds)
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=None,
        bundle_identifier="shop.messager.clickbait-parser",
        info_plist={
            "CFBundleDisplayName": "Clickbait Parser",
            "CFBundleName": APP_NAME,
            "CFBundleShortVersionString": "0.1.0",
            "NSHighResolutionCapable": True,
        },
    )
