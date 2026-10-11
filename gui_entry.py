#!/usr/bin/env python3
"""Windowed GUI entrypoint for PyInstaller builds."""

from __future__ import annotations

import sys


def main() -> int:
    from main import _run_gui

    return _run_gui(profile_id=None, threshold=0.5, page_size=100)


if __name__ == "__main__":
    raise SystemExit(main())
