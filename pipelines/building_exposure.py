"""Microsoft building-footprint density per zone (auxiliary to exposure).

Contract (mirrors pipelines/osm_exposure.py):
- Source: Microsoft Global ML Building Footprints, per-quadkey GeoJSONL
  shards listed in dataset-links.csv (ODbL 1.0; see
  minedbuildings.z5.web.core.windows.net/global-buildings). Shards are
  downloaded once to data/buildings/{location}/ and reused; the links
  file itself is cached at data/buildings/dataset-links.csv.
- A building counts once toward the zone containing its polygon
  centroid (smallest zones.id on multi-hit, same rule as
  osm_exposure.aggregate_zones, which this reuses for the density math:
  raw buildings/km2, never pre-normalized or pre-logged).
- Writes ONLY zones.building_density, in one transaction, after the
  full parse. The column is created if absent (same ensure-column
  pattern as seed_db's crater_class). priority_score/priority_rank and
  the three scoring components are never touched: building_density is
  an auxiliary settlement signal until a scoring decision blends it;
  pipelines/scoring.py does not read it.
- NULL semantics: a country whose shards were never parsed keeps NULL.
  A parsed country with zero buildings in a zone gets a real 0.0.
- The summary also reports the Pearson correlation with zones.exposure
  (where both exist) as a cross-check of the two settlement proxies;
  it is printed, never stored or scored.

Usage: python pipelines/building_exposure.py --country laos
"""

import csv
import gzip
import hashlib
import io
import json
import math
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # `python pipelines/building_exposure.py`

from backend.app.config import REPO_ROOT  # noqa: E402

LINKS_URL = "https://minedbuildings.z5.web.core.windows.net/global-buildings/dataset-links.csv"
BUILDINGS_DIR = REPO_ROOT / "data" / "buildings"
# ClearField country id -> Microsoft "Location" value in dataset-links.csv.
LOCATIONS = {"laos": "Laos", "cambodia": "Cambodia", "vietnam": "Vietnam", "ukraine": "Ukraine"}


def parse_size(text: str) -> float:
    """'213B' / '5.6MB' / '120.6MB' -> bytes (float; links sizes are rounded)."""
    text = text.strip()
    if text.endswith(("KB", "MB", "GB")):
        return float(text[:-2]) * {"KB": 1e3, "MB": 1e6, "GB": 1e9}[text[-2:]]
    if text.endswith("B"):
        return float(text[:-1])
    raise ValueError(f"unparsable size: {text!r}")


def load_links(links_path: Path | None = None) -> list[dict]:
    path = links_path or (BUILDINGS_DIR / "dataset-links.csv")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading dataset-links.csv -> {path}", flush=True)
        req = urllib.request.Request(LINKS_URL, headers={"User-Agent": "ClearField"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            path.write_bytes(resp.read())
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path) -> None:
    """Plain resumable download (Range), integrity left to gzip parsing."""
    import http.client
    import time
    import urllib.error

    total = None
    for attempt in range(1, 11):
        have = dest.stat().st_size if dest.exists() else 0
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ClearField"})
            if have:
                req.add_header("Range", f"bytes={have}-")
            with urllib.request.urlopen(req, timeout=300) as resp:
                if total is None and resp.headers.get("Content-Length"):
                    total = have + int(resp.headers["Content-Length"]) \
                        if resp.status == 206 else int(resp.headers["Content-Length"])
                mode = "ab" if (have and resp.status == 206) else "wb"
                if mode == "wb":
                    have = 0
                with dest.open(mode) as f:
                    for chunk in iter(lambda: resp.read(1 << 20), b""):
                        f.write(chunk)
            if total is None or dest.stat().st_size >= total:
                return
        except (urllib.error.URLError, http.client.HTTPException,
                ConnectionError, TimeoutError, OSError) as e:
            print(f"  {dest.name}: {type(e).__name__}: {e}; resuming", flush=True)
            time.sleep(5)
    raise SystemExit(f"download incomplete after 10 attempts: {dest}")


def download_shards(country_id: str, root: Path | None = None) -> list[Path]:
    """All quadkey shards for a country, cached under data/buildings/."""
    location = LOCATIONS[country_id]
    dest_root = (root or BUILDINGS_DIR) / location
    dest_root.mkdir(parents=True, exist_ok=True)
    manifest_path = dest_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) \
        if manifest_path.exists() else {}
    rows = [r for r in load_links() if r["Location"] == location]
    if not rows:
        raise FileNotFoundError(f"no Microsoft building shards for Location={location}")
    paths = []
    for i, r in enumerate(rows, 1):
        dest = dest_root / f"quadkey_{r['QuadKey']}.csv.gz"
        entry = manifest.get(dest.name)
        if dest.exists() and entry and entry.get("md5") == _md5(dest):
            paths.append(dest)
            continue
        print(f"[{country_id}] shard {i}/{len(rows)} {r['QuadKey']} ({r['Size']})",
              flush=True)
        _download(r["Url"], dest)
        manifest[dest.name] = {"url": r["Url"], "size_listed": r["Size"],
                               "bytes": dest.stat().st_size, "md5": _md5(dest)}
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        paths.append(dest)
    return paths


def iter_centroids(shard_paths, progress_every: int = 500_000):
    """Yield (lon, lat) building centroids from GeoJSONL .csv.gz shards."""
    import shapely
    from shapely.geometry import shape

    n = 0
    for path in shard_paths:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                geom = shape(json.loads(line)["geometry"])
                if geom.is_empty:
                    continue
                c = geom.centroid
                n += 1
                if progress_every and n % progress_every == 0:
                    print(f"  {n:,} buildings...", flush=True)
                yield (c.x, c.y)
    print(f"  {n:,} buildings total", flush=True)


def _pearson(xs, ys) -> float | None:
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    mx = sum(p[0] for p in pairs) / len(pairs)
    my = sum(p[1] for p in pairs) / len(pairs)
    cov = sum((x - mx) * (y - my) for x, y in pairs)
    vx = sum((x - mx) ** 2 for x, _ in pairs)
    vy = sum((y - my) ** 2 for _, y in pairs)
    if vx <= 0 or vy <= 0:
        return None
    return cov / math.sqrt(vx * vy)


def building_exposure_country(country_id: str, db_path=None,
                              shard_paths=None) -> dict:
    """Compute + write zones.building_density for one country."""
    import shapely
    from pyproj import Geod
    from shapely.geometry import shape

    from backend.app.db import get_conn
    from pipelines.osm_exposure import aggregate_zones

    if country_id not in LOCATIONS:
        raise ValueError(f"no building-footprint location for country: {country_id}")
    if shard_paths is None:
        shard_paths = download_shards(country_id)
    # Parse fully BEFORE opening/writing the DB: bad shards change nothing.
    points = list(iter_centroids(shard_paths))

    conn = get_conn(db_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(zones)")}
        rows = [dict(r) for r in conn.execute(
            "SELECT id, geom, exposure FROM zones WHERE country = ? ORDER BY id",
            (country_id,))]
        geod = Geod(ellps="WGS84")
        zones = []
        for row in rows:
            geom = shapely.make_valid(shape(json.loads(row["geom"])))
            zones.append({"id": row["id"], "geom": geom,
                          "area_km2": abs(geod.geometry_area_perimeter(geom)[0]) / 1e6,
                          "_exposure": row["exposure"]})
        density, counters = aggregate_zones(zones, points)
        for zid, value in density.items():
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"zone {zid}: building_density must be finite >= 0, got {value!r}")
        with conn:
            if "building_density" not in cols:
                conn.execute("ALTER TABLE zones ADD COLUMN building_density REAL")
            conn.executemany(
                "UPDATE zones SET building_density = ? WHERE id = ?",
                [(density[z["id"]], z["id"]) for z in zones])
    finally:
        conn.close()
    values = list(density.values())
    corr = _pearson([density[z["id"]] for z in zones],
                    [z["_exposure"] for z in zones])
    return {
        "country": country_id,
        "zones": len(zones),
        "zones_with_buildings": sum(1 for v in values if v > 0),
        "zones_zero": sum(1 for v in values if v == 0),
        "density_min": min(values) if values else None,
        "density_max": max(values) if values else None,
        "buildings": counters["assigned"] + counters["outside"],
        "assigned": counters["assigned"],
        "outside": counters["outside"],
        "multi_hit": counters["multi_hit"],
        "exposure_correlation": corr,
        "shards": [str(p) for p in shard_paths],
    }


if __name__ == "__main__":
    from pipelines._profile import country_arg

    profile = country_arg()
    try:
        summary = building_exposure_country(profile["id"])
    except (FileNotFoundError, ValueError) as exc:
        print(f"[building_exposure] {exc}", file=sys.stderr)
        print("[building_exposure] no zones updated; building_density left as-is (NULL).",
              file=sys.stderr)
        sys.exit(1)
    print(f"[building_exposure] {summary['country']}: {summary['zones']} zones, "
          f"{summary['zones_with_buildings']} with buildings>0, "
          f"{summary['zones_zero']} at 0.0 "
          f"(min {summary['density_min']:.6g}, max {summary['density_max']:.6g} buildings/km2)")
    print(f"[building_exposure] buildings {summary['buildings']:,} = assigned "
          f"{summary['assigned']:,} + outside {summary['outside']:,}; "
          f"multi-hit {summary['multi_hit']:,}")
    if summary["exposure_correlation"] is not None:
        print(f"[building_exposure] Pearson r(building_density, exposure) = "
              f"{summary['exposure_correlation']:.3f} (cross-check only, not scored)")
    print("[building_exposure] priority scores untouched; "
          "building_density is auxiliary until a scoring decision uses it.")
