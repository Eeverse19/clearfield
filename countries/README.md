# Country profiles

Country is a configuration, never code. One JSON file per country; pipelines and
the backend take `--country <id>` / `?country=<id>` and read everything
country-specific from here. If adding a country needs a code change, that is a
design bug — fix the design, not the country.

## Fields

| Field | Meaning |
|---|---|
| `id` | Short id, must match the filename (`laos.json` -> `laos`) |
| `name` | Display name |
| `languages` | Query/report languages, e.g. `["en", "lo"]` |
| `demo_area` | Demo province, matching GADM `admin_name` where set (`Xiangkhoang`, `Tbong Khmum`). `null` if unset. |
| `strike_source` | `{type, dataset, country_filter}` — THOR for Tier 1, UCDP/ACLED later |
| `imagery` | Image sets used for tiling/segmentation, in preference order |
| `boundaries` | Boundary source (GADM) and admin level used for zones |
| `osm_extract` | OSM extract for exposure: repo-relative `data/osm/<name>-<YYMMDD>.osm.pbf` path (pinned), or bare slug until pinned |
| `stats_source` | Published province-level statistics (never IMSMA polygons) |
| `_todo` | Unresolved items; empty list means the profile is data-complete |

Scoring weights are deliberately not a profile field yet. The implemented
contract (`pipelines/scoring.py`, WORKFLOW_SYNTHESIS.md §2) normalizes each
component per country (`log1p(x)/log1p(max)`), takes the product, and applies
a surveyed-status factor (provisional values, owner to freeze). Until real
data shows a country needs different weights, do not invent weights here.
