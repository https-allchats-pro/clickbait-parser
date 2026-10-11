#!/usr/bin/env python3
"""Windowed GUI entrypoint for PyInstaller builds."""

from __future__ import annotations

import sys


def main() -> int:
    # Must run before any UI: handles Velopack install/update/uninstall hooks
    # (the process may exit here) and is a no-op outside a Velopack install.
    import velopack

    velopack.App().run()

    from main import _run_gui

    return _run_gui(profile_id=None, threshold=0.5, page_size=100)


if __name__ == "__main__":
    raise SystemExit(main())
