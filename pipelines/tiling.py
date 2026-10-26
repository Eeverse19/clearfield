"""Imagery -> 256x256 tiles for a country profile. Scaffold stub."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # `python pipelines/tiling.py`

from pipelines._profile import country_arg, not_implemented  # noqa: E402

if __name__ == "__main__":
    not_implemented("tiling", country_arg(), "downloaded imagery under data/imagery/")
