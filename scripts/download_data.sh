#!/usr/bin/env bash
# Thin wrapper: implementation is scripts/download_data.py (stdlib only).
# Usage: scripts/download_data.sh [file.zip ...]  (no args = all pinned files)
set -euo pipefail
cd "$(dirname "$0")/.."
if command -v uv >/dev/null 2>&1; then exec uv run python scripts/download_data.py "$@"
else exec python3 scripts/download_data.py "$@"; fi
