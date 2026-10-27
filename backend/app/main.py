"""ClearField API.

Implemented: health, country profiles, GET /zones and POST /finds over the
local SQLite DB (WORKFLOW_SYNTHESIS.md section 3). Not implemented: /explain
(needs META_API_KEY + Spark wiring) — it keeps returning 501 with the reason.
Nothing here invents zones, scores, or explanations; missing DB is 503.
Handlers (list_zones/create_find) are plain functions so tests can call them
directly with a tmp DB (sandboxed shells cannot open TestClient sockets).
"""

import json
import sqlite3
from datetime import datetime, timezone

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

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


@app.post("/explain")
def explain() -> dict:
    if not config.META_API_KEY:
        raise HTTPException(
            status_code=501,
            detail="explain not implemented: META_API_KEY not set (Spark runs on stored score components only)",
        )
    raise HTTPException(status_code=501, detail="explain not implemented: Spark agent not wired yet")
