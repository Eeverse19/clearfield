"""ClearField API.

Implemented: health, country profiles, GET /zones and POST /finds over the
local SQLite DB (WORKFLOW_SYNTHESIS.md section 3). /explain is cache-first:
seeded templates over stored score components (no META_API_KEY needed),
501 only on a cache miss; live Spark is still not wired.
Nothing here invents zones, scores, or explanations; missing DB is 503.
Handlers (list_zones/create_find/explain_request) are plain functions so tests can call them
directly with a tmp DB (sandboxed shells cannot open TestClient sockets).
"""

import array
import math
import re

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response

from backend.app import config
from backend.app.db import get_conn
from backend.app.profiles import list_countries, load_country

app = FastAPI(title="ClearField", version="0.0.0")

FRONTEND_INDEX = config.REPO_ROOT / "frontend" / "index.html"


@app.get("/")
def index():
    """Serve the single-file map GUI (frontend/index.html) at the root."""
    if not FRONTEND_INDEX.exists():
        raise HTTPException(status_code=404, detail="frontend/index.html not found")
    return FileResponse(FRONTEND_INDEX, media_type="text/html")

SURVEYED_STATUSES = ("unsurveyed", "surveyed", "cleared")
RISK_FLAGS = ("unknown", "suspect_live", "inert", "escalated")
FIND_FIELDS = ("id", "country", "zone_id", "object_type", "condition",
               "estimated_size", "risk_flag", "location", "notes", "photo_ref",
               "recorded_at")
DB_MISSING = ("local DB unavailable (CLEARFIELD_LOCAL_DB="
              f"{config.LOCAL_DB_PATH}); run scripts/seed_db.ps1 first")

# --- /explain (cache-first; see demo/cached-responses/README.md) -----------
EXPLAIN_FIELDS = ("zone_id", "country", "lang")
# Union of countries/*.json languages; deliberately not restricted
# per-country so a Laos zone can be asked about in Khmer (demo Moment 2).
EXPLAIN_LANGS = ("en", "lo", "km", "vi")
ZONE_ID_RE = re.compile(r"^[A-Z]{3}\.[0-9]+_[0-9]+$")  # GADM GID_1 shape
# Country ids are lowercase profile stems (laos/cambodia/vietnam). Anything
# else is malformed input, never a filesystem path (critic defect 1).
COUNTRY_ID_RE = re.compile(r"^[a-z]+$")
EXPLAIN_ORIGIN = "template_from_stored_components"
EXPLAIN_GENERATED_FROM = ("stored score components only "
                          "(pipelines/scoring.py); no live model")
EXPLAIN_COMPONENT_FIELDS = ("strike_density", "crater_evidence", "exposure",
                            "surveyed_status", "priority_score",
                            "priority_rank", "scored_at")
EXPLAIN_NUMERIC_FIELDS = ("strike_density", "crater_evidence", "exposure",
                          "priority_score")
EXPLAIN_FILE_FIELDS = ("schema_version", "kind", "zone_id", "country",
                       "admin_name", "lang", "explanation",
                       "score_components", "origin", "generated_from")


def _country_or_404(country_id: str) -> dict:
    try:
        return load_country(country_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"unknown country: {country_id}")


def _conn_or_503(db_path, *, readonly: bool):
    try:
        return get_conn(db_path, readonly=readonly)
    except (FileNotFoundError, sqlite3.Error):
        raise HTTPException(status_code=503, detail=DB_MISSING)


def _parse_geojson(value):
    return json.loads(value) if isinstance(value, str) else value


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "scaffold": True,
        "meta_api_key_set": bool(config.META_API_KEY),
        "database_url_set": bool(config.DATABASE_URL),
        "local_db": str(config.LOCAL_DB_PATH),
        "local_db_exists": config.LOCAL_DB_PATH.exists(),
    }


@app.get("/countries")
def countries() -> list[dict]:
    return list_countries()


@app.get("/countries/{country_id}")
def country(country_id: str) -> dict:
    return _country_or_404(country_id)


def list_zones(country: str = "laos", surveyed_status: str | None = None,
               include_unscored: bool = True, limit: int = 100, offset: int = 0,
               db_path=None) -> dict:
    _country_or_404(country)
    if surveyed_status is not None and surveyed_status not in SURVEYED_STATUSES:
        raise HTTPException(status_code=422, detail=f"invalid surveyed_status: {surveyed_status!r}")
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be in 1..500")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be >= 0")
    where, params = ["country = ?"], [country]
    if surveyed_status is not None:
        where.append("surveyed_status = ?")
        params.append(surveyed_status)
    if not include_unscored:
        where.append("priority_rank IS NOT NULL")
    clause = " AND ".join(where)
    conn = _conn_or_503(db_path, readonly=True)
    try:
        total = conn.execute(f"SELECT COUNT(*) FROM zones WHERE {clause}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM zones WHERE {clause}"
            " ORDER BY (priority_rank IS NULL), priority_rank ASC, id ASC LIMIT ? OFFSET ?",
            [*params, limit, offset]).fetchall()
    except sqlite3.Error:
        raise HTTPException(status_code=503, detail=DB_MISSING)
    finally:
        conn.close()
    zones = [{**dict(r), "geom": _parse_geojson(r["geom"])} for r in rows]
    return {"country": country, "count": len(zones), "total": total, "zones": zones}


@app.get("/zones")
def zones(country: str = "laos", surveyed_status: str | None = None,
          include_unscored: bool = True, limit: int = 100, offset: int = 0) -> dict:
    return list_zones(country, surveyed_status, include_unscored, limit, offset)


# Building centroids (Microsoft footprints) for the GUI overlay. Points
# live in data/buildings/{Location}/centroids.f32 (float32-le lon,lat
# pairs) made by scripts/make_building_points.py; polygons/density are
# pipelines/building_exposure.py's job, this endpoint only serves dots.
BUILDING_LOCATIONS = {"laos": "Laos", "cambodia": "Cambodia",
                      "vietnam": "Vietnam", "ukraine": "Ukraine"}


def get_buildings(country: str, bbox: str | None = None, limit: int = 2_000_000,
                  buildings_dir=None) -> Response:
    if country not in BUILDING_LOCATIONS:
        raise HTTPException(status_code=404, detail=f"unknown country: {country}")
    if not 1 <= limit <= 5_000_000:
        raise HTTPException(status_code=422, detail="limit must be in 1..5000000")
    bounds = None
    if bbox:
        try:
            bounds = tuple(float(x) for x in bbox.split(","))
            assert len(bounds) == 4 and bounds[0] < bounds[2] and bounds[1] < bounds[3]
        except (ValueError, AssertionError):
            raise HTTPException(status_code=422,
                                detail="bbox must be minlon,minlat,maxlon,maxlat")
    root = buildings_dir if buildings_dir is not None else \
        config.REPO_ROOT / "data" / "buildings"
    path = root / BUILDING_LOCATIONS[country] / "centroids.f32"
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"building points not generated for {country}: run "
                   f"scripts/make_building_points.py --country {country} first")
    try:
        import numpy as np

        arr = np.fromfile(path, dtype="<f4").reshape(-1, 2)
        total = int(arr.shape[0])
        if bounds:
            mask = ((arr[:, 0] >= bounds[0]) & (arr[:, 0] <= bounds[2])
                    & (arr[:, 1] >= bounds[1]) & (arr[:, 1] <= bounds[3]))
            arr = arr[mask]
        truncated = bool(arr.shape[0] > limit)
        body = arr[:limit].astype("<f4").tobytes()
        return Response(
            content=body, media_type="application/octet-stream",
            headers={"X-Building-Count": str(min(int(arr.shape[0]), limit)),
                     "X-Building-Total": str(total),
                     "X-Building-Truncated": str(truncated).lower()})
    except ImportError:  # pragma: no cover - numpy ships with shapely deps
        pass
    pts = array.array("f")
    with path.open("rb") as fh:
        pts.frombytes(fh.read())
    total = len(pts) // 2
    out = array.array("f")
    truncated = False
    for i in range(total):
        lon, lat = pts[2 * i], pts[2 * i + 1]
        if bounds and not (bounds[0] <= lon <= bounds[2] and bounds[1] <= lat <= bounds[3]):
            continue
        if len(out) // 2 >= limit:
            truncated = True
            break
        out.extend((lon, lat))
    return Response(
        content=out.tobytes(), media_type="application/octet-stream",
        headers={"X-Building-Count": str(len(out) // 2),
                 "X-Building-Total": str(total),
                 "X-Building-Truncated": str(truncated).lower()})


@app.get("/buildings/{country}")
def buildings(country: str, bbox: str | None = None, limit: int = 2_000_000):
    return get_buildings(country, bbox, limit)


def _validate_location(location):
    if location is None:
        return None
    ok = (isinstance(location, dict) and location.get("type") == "Point"
          and isinstance(location.get("coordinates"), (list, tuple))
          and len(location["coordinates"]) == 2
          and all(isinstance(c, (int, float)) and not isinstance(c, bool)
                  for c in location["coordinates"])
          and -180 <= location["coordinates"][0] <= 180
          and -90 <= location["coordinates"][1] <= 90)
    if not ok:
        raise HTTPException(status_code=422,
                            detail="location must be a GeoJSON Point [lon, lat] in range")
    return {"type": "Point", "coordinates": list(location["coordinates"])}


def create_find(payload: dict, db_path=None) -> tuple[dict, int]:
    """Store one already-structured find record. Returns (record, status).

    The endpoint stores and echoes only; it never re-ranks zones (re-scoring
    is pipelines/scoring.py) and never advises approaching a suspect item.
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="payload must be a JSON object")
    extra = set(payload) - set(FIND_FIELDS)
    if extra:
        raise HTTPException(status_code=422,
                            detail=f"unknown fields (synced_at is server-set): {sorted(extra)}")
    for required in ("id", "country"):
        if not payload.get(required):
            raise HTTPException(status_code=422, detail=f"{required} is required")
    _country_or_404(payload["country"])
    risk_flag = payload.get("risk_flag", "unknown")
    if risk_flag not in RISK_FLAGS:
        raise HTTPException(status_code=422, detail=f"invalid risk_flag: {risk_flag!r}")
    location = _validate_location(payload.get("location"))
    record = {f: payload.get(f) for f in FIND_FIELDS}
    record.update(risk_flag=risk_flag, location=location)
    conn = _conn_or_503(db_path, readonly=False)
    try:
        if record["zone_id"] is not None:
            hit = conn.execute("SELECT 1 FROM zones WHERE id = ? AND country = ?",
                                (record["zone_id"], record["country"])).fetchone()
            if hit is None:
                raise HTTPException(status_code=422,
                                    detail=f"unknown zone_id for {record['country']}: {record['zone_id']}")
        existing = conn.execute("SELECT * FROM finds WHERE id = ?", (record["id"],)).fetchone()
        if existing is not None:
            stored = {**dict(existing), "location": _parse_geojson(existing["location"])}
            if all(stored[f] == record[f] for f in FIND_FIELDS):
                return stored, 200  # identical offline replay
            raise HTTPException(status_code=409,
                                detail=f"find id already exists with different content: {record['id']}")
        record["synced_at"] = datetime.now(timezone.utc).isoformat()
        with conn:
            conn.execute(
                "INSERT INTO finds (id, country, zone_id, object_type, condition,"
                " estimated_size, risk_flag, location, notes, photo_ref, recorded_at,"
                " synced_at) VALUES (:id, :country, :zone_id, :object_type, :condition,"
                " :estimated_size, :risk_flag, :location_json, :notes, :photo_ref,"
                " :recorded_at, :synced_at)",
                {**record, "location_json": json.dumps(location) if location else None})
    except sqlite3.Error:
        raise HTTPException(status_code=503, detail=DB_MISSING)
    finally:
        conn.close()
    return record, 201


@app.post("/finds", status_code=201)
def post_finds(payload: dict = Body(...)):
    record, status = create_find(payload)
    if status == 200:
        return JSONResponse(record, status_code=200)
    return record


def _fmt_component(value) -> str:
    return format(value, ".6g") if isinstance(value, (int, float)) \
        and not isinstance(value, bool) else "not stored"


def render_explanation(row: dict) -> str:
    """Frozen English template over one stored zone row (Spec 6).

    Shared by scripts/make_cached_explanations.py (writer) and
    tests/test_cached_explanations.py (verifier) so seeded text can never
    drift from the stored components it cites. Only stored values appear;
    normalized components exist only in memory (pipelines/scoring.py).
    """
    return (
        f"{row['admin_name']} ({row['id']}, {row['country']}) is ranked "
        f"#{row['priority_rank']} with priority score "
        f"{_fmt_component(row['priority_score'])}. Its stored score "
        f"components are strike density "
        f"{_fmt_component(row['strike_density'])} recorded missions/km² "
        f"(USAF THOR records), crater evidence "
        f"{_fmt_component(row['crater_evidence'])} craters/km² (KH-9 "
        f"imagery crater predictions), and exposure "
        f"{_fmt_component(row['exposure'])} OSM features/km² "
        f"(OpenStreetMap). Surveyed status: {row['surveyed_status']}. "
        f"The score was computed by pipelines/scoring.py at "
        f"{row['scored_at']}; this cached explanation only restates those "
        f"stored values and is not a live model answer.")


def build_cached_explanation(row: dict, lang: str = "en") -> dict:
    """The exact on-disk payload for one (zone, lang) cache file."""
    return {
        "schema_version": 1,
        "kind": "explain",
        "zone_id": row["id"],
        "country": row["country"],
        "admin_name": row["admin_name"],
        "lang": lang,
        "explanation": render_explanation(row),
        "score_components": {f: row[f] for f in EXPLAIN_COMPONENT_FIELDS},
        "origin": EXPLAIN_ORIGIN,
        "generated_from": EXPLAIN_GENERATED_FROM,
    }



def _cached_explain_path(cached_dir, zone_id: str, lang: str) -> Path:
    root = Path(cached_dir) if cached_dir is not None \
        else config.CACHED_RESPONSES_DIR
    # Built only from the regex-validated zone_id + allowlisted lang;
    # the resolve check is defense in depth (Spec 5).
    path = root / f"explain-{zone_id}-{lang}.json"
    if path.resolve().parent != root.resolve():
        raise HTTPException(status_code=422,
                            detail=f"invalid zone_id: {zone_id!r}")
    return path


def _is_stored_number(value) -> bool:
    # bool is rejected for every numeric component (critic defect 5,
    # mirroring pipelines/scoring.py): JSON true must never equal 1.0.
    return value is None or (isinstance(value, (int, float))
                              and not isinstance(value, bool)
                              and math.isfinite(value))


def _load_cached_explain(cached_dir, zone_row: dict, lang: str):
    """Validated cache payload, or None for absent/stale (a miss).

    A file that exists but is malformed is a server data fault (503):
    never served and never silently treated as a miss.
    """
    path = _cached_explain_path(cached_dir, zone_row["id"], lang)
    if not path.exists():
        return None

    def unreadable():
        return HTTPException(
            status_code=503,
            detail=f"cached explanation unreadable: {path.name}")

    try:
        # utf-8 is pinned: seeded names/km² are non-ASCII and the Windows
        # default (cp1252) would serve mojibake (critic defect 2).
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise unreadable()
    if not isinstance(data, dict) or set(data) != set(EXPLAIN_FILE_FIELDS):
        raise unreadable()
    if type(data["schema_version"]) is not int \
            or data["schema_version"] != 1 \
            or data["kind"] != "explain" \
            or data["origin"] != EXPLAIN_ORIGIN \
            or data["generated_from"] != EXPLAIN_GENERATED_FROM:
        raise unreadable()
    if data["zone_id"] != zone_row["id"] \
            or data["country"] != zone_row["country"] \
            or data["admin_name"] != zone_row["admin_name"] \
            or data["lang"] != lang:
        raise unreadable()
    if not isinstance(data["explanation"], str) or not data["explanation"]:
        raise unreadable()
    components = data["score_components"]
    if not isinstance(components, dict) \
            or set(components) != set(EXPLAIN_COMPONENT_FIELDS):
        raise unreadable()
    if any(not _is_stored_number(components[f])
           for f in EXPLAIN_NUMERIC_FIELDS):
        raise unreadable()
    rank = components["priority_rank"]
    if rank is not None and (isinstance(rank, bool)
                             or not isinstance(rank, int)):
        raise unreadable()
    if components["surveyed_status"] not in SURVEYED_STATUSES:
        raise unreadable()
    if components["scored_at"] is not None \
            and not isinstance(components["scored_at"], str):
        raise unreadable()
    # English text must be exactly the frozen template over the current
    # DB row, so renamed zones / hand-edited text are never served as
    # fact (critic defect 4). No non-en template exists yet.
    if lang == "en" and data["explanation"] != render_explanation(zone_row):
        raise unreadable()
    current = {f: zone_row[f] for f in EXPLAIN_COMPONENT_FIELDS}
    if components != current:
        return None  # stale: re-scored since seeding -> miss, never old text
    return data


def explain_request(payload, db_path=None, cached_dir=None) -> dict:
    """Cache-first /explain handler (plain function, mirroring create_find).

    Statuses: 200 cache hit; 501 cache miss (live Spark unwired, with or
    without META_API_KEY); 422 malformed input / traversal-shaped ids /
    unknown zone; 404 unknown country; 503 DB missing or malformed cache
    file. The cache is checked before META_API_KEY, so a hit needs no key.
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422,
                            detail="payload must be a JSON object")
    extra = set(payload) - set(EXPLAIN_FIELDS)
    if extra:
        raise HTTPException(status_code=422,
                            detail=f"unknown fields: {sorted(extra)}")
    if "zone_id" not in payload:
        raise HTTPException(status_code=422, detail="zone_id is required")
    zone_id = payload["zone_id"]
    if not isinstance(zone_id, str) or not zone_id.strip() \
            or not ZONE_ID_RE.fullmatch(zone_id):
        raise HTTPException(status_code=422,
                            detail=f"invalid zone_id: {zone_id!r}")
    country = payload.get("country")
    if "country" in payload:
        if not isinstance(country, str) or not country \
                or not COUNTRY_ID_RE.fullmatch(country):
            raise HTTPException(status_code=422,
                                detail=f"invalid country: {country!r}")
        try:
            _country_or_404(country)
        except ValueError:  # malformed profile must never surface as 500
            raise HTTPException(status_code=404,
                                detail=f"unknown country: {country}")
    lang = payload.get("lang", "en")
    if not isinstance(lang, str):
        raise HTTPException(status_code=422, detail=f"invalid lang: {lang!r}")
    requested_lang = lang.strip().lower()
    if requested_lang not in EXPLAIN_LANGS:
        raise HTTPException(status_code=422, detail=f"invalid lang: {lang!r}")

    sql = ("SELECT id, country, admin_name, strike_density, "
           "crater_evidence, exposure, surveyed_status, priority_score, "
           "priority_rank, scored_at FROM zones WHERE id = ?")
    params = [zone_id]
    if country is not None:
        sql += " AND country = ?"
        params.append(country)
    conn = _conn_or_503(db_path, readonly=True)
    try:
        row = conn.execute(sql, params).fetchone()
    except sqlite3.Error:
        raise HTTPException(status_code=503, detail=DB_MISSING)
    finally:
        conn.close()
    if row is None:
        if country is not None:
            raise HTTPException(
                status_code=422,
                detail=f"unknown zone_id for {country}: {zone_id}")
        raise HTTPException(status_code=422,
                            detail=f"unknown zone_id: {zone_id}")
    zone_row = dict(row)

    served = _load_cached_explain(cached_dir, zone_row, requested_lang)
    served_lang = requested_lang
    if served is None and requested_lang != "en":
        served = _load_cached_explain(cached_dir, zone_row, "en")
        served_lang = "en"
    if served is not None:
        return {
            "zone_id": zone_row["id"],
            "country": zone_row["country"],
            "admin_name": zone_row["admin_name"],
            "lang": served_lang,
            "requested_lang": requested_lang,
            "source": "cache",
            "origin": EXPLAIN_ORIGIN,
            "explanation": served["explanation"],
            "score_components": {f: zone_row[f]
                                  for f in EXPLAIN_COMPONENT_FIELDS},
        }
    if not (config.META_API_KEY):  # cache miss and no key for live Spark
        raise HTTPException(
            status_code=501,
            detail="explain not implemented: META_API_KEY not set (Spark runs on stored score components only)")
    raise HTTPException(
        status_code=501,
        detail="explain not implemented: Spark agent not wired yet")


@app.post("/explain")
def explain(payload: dict = Body(...)) -> dict:
    return explain_request(payload)
