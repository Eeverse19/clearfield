#!/usr/bin/env bash
# Thin wrapper: implementation is scripts/seed_thor.py (needs the THOR CSV extracted
# into data/thor/ first - see "python scripts/seed_thor.py --help" / spec §2.1).
# Usage: scripts/seed_thor.sh [--country ID] [--csv PATH] [--db PATH] [--dry-run]
set -euo pipefail
cd "$(dirname "$0")/.."
if command -v uv >/dev/null 2>&1; then exec uv run python scripts/seed_thor.py "$@"
else exec python3 scripts/seed_thor.py "$@"; fi
