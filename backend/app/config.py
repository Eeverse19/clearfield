"""Runtime config from environment (.env is loaded by uvicorn/shell, not code)."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COUNTRIES_DIR = REPO_ROOT / "countries"
CACHED_RESPONSES_DIR = REPO_ROOT / "demo" / "cached-responses"

META_API_KEY = os.environ.get("META_API_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
LOCAL_DB_PATH = REPO_ROOT / os.environ.get("CLEARFIELD_LOCAL_DB", "data/clearfield.db")
