#!/usr/bin/env bash
# Build macOS ClickbaitParser.app → dist/release/*.zip
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec "${ROOT}/.venv/bin/python" scripts/build_release.py --os macos --clean "$@"
