#!/usr/bin/env bash
# Thin wrapper: implementation is scripts/seed_db.py (needs downloads first:
# scripts/download_data.sh predictions.zip gadm41_LAO_1.json gadm41_KHM_1.json gadm41_VNM_1.json).
set -euo pipefail
cd "$(dirname "$0")/.."
if command -v uv >/dev/null 2>&1; then exec uv run python scripts/seed_db.py
else exec python3 scripts/seed_db.py; fi
