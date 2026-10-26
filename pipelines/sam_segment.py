"""SAM 3.1 crater segmentation -> masks -> GeoJSON, cached per tile.

Scaffold stub. SAM sees only: it must not decide risk or explain anything.
Runs batched (Modal), once per tile, never re-runs a cached tile.
Needs META_API_KEY (not yet provided) and tiling output.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # `python pipelines/sam_segment.py`

from pipelines._profile import country_arg, not_implemented  # noqa: E402

if __name__ == "__main__":
    not_implemented("sam_segment", country_arg(), "META_API_KEY and pipelines/tiling.py output")
