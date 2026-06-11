"""OSINT Energy Security Dashboard — routes and data-ingest endpoints.

Registered in app.py as a separate Blueprint so this file never touches
the existing routes.py or any other curator code.

API surface:
  GET  /dashboard                   — serves the dashboard SPA
  GET  /api/osint/health            — liveness check
  GET  /api/osint/assets            — infrastructure asset layer (GeoJSON)
  GET  /api/osint/assets/types      — asset type counts
  POST /api/osint/assets/ingest     — bulk upsert (X-API-Key required)
  GET  /api/osint/grid/current      — latest fuel-mix snapshot per ISO
  POST /api/osint/grid/ingest       — receive grid snapshot rows (X-API-Key required)
  GET  /api/osint/incidents         — recent pipeline/cyber/nuclear incidents
  POST /api/osint/incidents/ingest  — bulk upsert incidents (X-API-Key required)
  GET  /api/osint/news              — recent articles from the curator Article table
  GET  /api/osint/regions           — ISO/RTO region boundaries (proxied from HIFLD)
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Any

from flask import Blueprint, jsonify, render_template, request, Response
from sqlalchemy import func, text


def _qint(key: str, default: int, max_val: int | None = None) -> int:
    try:
        n = int(request.args.get(key, default))
    except (ValueError, TypeError):
        n = default
    return min(n, max_val) if max_val is not None else n

from app import db
from models import Article
from osint_models import OsintAsset, OsintGridAlert, OsintGridSnapshot, OsintIncident

osint_bp = Blueprint("osint", __name__)


# ── Auth helper ───────────────────────────────────────────────────────────────

def _ingest_auth_ok() -> bool:
    expected = os.environ.get("INGEST_API_KEY", "")
    return bool(expected) and request.headers.get("X-API-Key", "") == expected


# ── Dashboard page ────────────────────────────────────────────────────────────

@osint_bp.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


# ── Health ────────────────────────────────────────────────────────────────────

@osint_bp.route("/api/osint/health")
def osint_health():
    try:
        db.session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return jsonify({"status": "ok" if db_ok else "degraded", "db": db_ok})


# ── Assets ────────────────────────────────────────────────────────────────────

@osint_bp.route("/api/osint/assets")
def osint_assets():
    asset_type = request.args.get("type")
    state      = request.args.get("state")
    limit      = _qint("limit", 5000, 25000)

    q = OsintAsset.query
    if asset_type:
        q = q.filter_by(type=asset_type)
    if state:
        q = q.filter_by(state=state.upper())
    q = q.order_by(OsintAsset.type, OsintAsset.name).limit(limit)

    features = [a.to_geojson_feature() for a in q.all()]
    return jsonify({"type": "FeatureCollection", "features": features})


@osint_bp.route("/api/osint/assets/types")
def osint_asset_types():
    rows = (
        db.session.query(OsintAsset.type, func.count(OsintAsset.id).label("count"))
        .group_by(OsintAsset.type)
        .order_by(func.count(OsintAsset.id).desc())
        .all()
    )
    return jsonify([{"type": r.type, "count": r.count} for r in rows])


@osint_bp.route("/api/osint/assets/ingest", methods=["POST"])
def osint_assets_ingest():
    if not _ingest_auth_ok():
        return jsonify({"error": "unauthorized"}), 401

    data   = request.get_json(silent=True) or {}
    assets = data.get("assets", [])
    if not assets:
        return jsonify({"error": "no assets provided"}), 400

    upserted = 0
    now = datetime.now(timezone.utc)
    for a in assets:
        asset_id = a.get("id")
        if not asset_id or not a.get("type"):
            continue
        existing = OsintAsset.query.get(asset_id)
        if existing:
            for field in ("source", "source_id", "name", "state", "county", "lat", "lng",
                          "geometry_wkt", "capacity_mw", "fuel_type", "operator", "owner",
                          "status", "voltage_kv", "metadata_json", "foreign_link_flag"):
                if field in a:
                    setattr(existing, field, a[field])
            existing.updated_at = now
        else:
            db.session.add(OsintAsset(
                id=asset_id,
                source=a.get("source", "manual"),
                source_id=a.get("source_id"),
                type=a["type"],
                name=a.get("name"),
                state=a.get("state"),
                county=a.get("county"),
                lat=a.get("lat"),
                lng=a.get("lng"),
                geometry_wkt=a.get("geometry_wkt"),
                capacity_mw=a.get("capacity_mw"),
                fuel_type=a.get("fuel_type"),
                operator=a.get("operator"),
                owner=a.get("owner"),
                status=a.get("status"),
                voltage_kv=a.get("voltage_kv"),
                metadata_json=json.dumps(a.get("metadata") or {}),
                foreign_link_flag=bool(a.get("foreign_link_flag", False)),
                updated_at=now,
            ))
        upserted += 1

    db.session.commit()
    return jsonify({"upserted": upserted})


# ── Grid telemetry ────────────────────────────────────────────────────────────

@osint_bp.route("/api/osint/grid/current")
def osint_grid_current():
    """Return the most recent snapshot per (region, source, metric, fuel).

    Optional query params:
      ?source=gridstatus|eia930   — filter to one source
      ?region=ERCO                — filter to one BA/ISO region code
      ?metric=fuel_mix_mw         — filter to one metric
    """
    source_filter = request.args.get("source")
    region_filter = request.args.get("region")
    metric_filter = request.args.get("metric")

    where_parts: list[str] = []
    params: dict[str, str] = {}
    if source_filter:
        where_parts.append("AND g.source = :source")
        params["source"] = source_filter
    if region_filter:
        where_parts.append("AND g.region = :region")
        params["region"] = region_filter
    if metric_filter:
        where_parts.append("AND g.metric = :metric")
        params["metric"] = metric_filter
    where_extra = " ".join(where_parts)

    rows = db.session.execute(text(f"""
        SELECT g.region, g.region_type, g.source, g.timestamp, g.metric, g.fuel, g.value, g.unit
        FROM osint_grid_snapshots g
        JOIN (
            SELECT region, source, metric, fuel, MAX(timestamp) AS max_ts
            FROM osint_grid_snapshots
            GROUP BY region, source, metric, fuel
        ) latest
          ON g.region    = latest.region
         AND g.source    = latest.source
         AND g.metric    = latest.metric
         AND g.fuel      = latest.fuel
         AND g.timestamp = latest.max_ts
        WHERE 1=1 {where_extra}
        ORDER BY g.region, g.source, g.metric, g.fuel
    """), params).fetchall()

    payload: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        ts = r.timestamp
        item = {
            "region_type": r.region_type,
            "source":      r.source,
            "timestamp":   ts.isoformat() if isinstance(ts, datetime) else str(ts),
            "metric":      r.metric,
            "fuel":        r.fuel,
            "value":       r.value,
            "unit":        r.unit,
        }
        payload.setdefault(r.region, []).append(item)
    return jsonify(payload)


@osint_bp.route("/api/osint/grid/ingest", methods=["POST"])
def osint_grid_ingest():
    """Receive grid snapshot rows from aggregator push scripts.

    Accepts unified row shape:
      region, region_type, source, timestamp, metric, fuel, value, unit
    Also accepts legacy `iso` field (maps to region; source defaults to gridstatus).
    """
    if not _ingest_auth_ok():
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    rows = data.get("rows", [])
    if not rows:
        return jsonify({"inserted": 0})

    inserted = 0
    for row in rows:
        region      = row.get("region") or row.get("iso", "")
        region_type = row.get("region_type", "iso")
        source      = row.get("source", "gridstatus")
        metric      = row.get("metric", "")
        fuel        = str(row.get("fuel") or "")
        value       = row.get("value")
        unit        = row.get("unit")

        if not region or value is None:
            continue

        raw_ts = row.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            ts = datetime.utcnow()

        db_url = db.engine.url.drivername
        if "postgresql" in db_url or "postgres" in db_url:
            db.session.execute(text("""
                INSERT INTO osint_grid_snapshots
                  (region, region_type, source, timestamp, metric, fuel, value, unit, metadata_json, created_at)
                VALUES (:region, :region_type, :source, :ts, :metric, :fuel, :value, :unit, '{}', NOW())
                ON CONFLICT (region, timestamp, metric, fuel, source) DO NOTHING
            """), {"region": region, "region_type": region_type, "source": source,
                   "ts": ts, "metric": metric, "fuel": fuel,
                   "value": float(value), "unit": unit or ""})
        else:
            db.session.execute(text("""
                INSERT OR IGNORE INTO osint_grid_snapshots
                  (region, region_type, source, timestamp, metric, fuel, value, unit, metadata_json, created_at)
                VALUES (:region, :region_type, :source, :ts, :metric, :fuel, :value, :unit, '{}', datetime('now'))
            """), {"region": region, "region_type": region_type, "source": source,
                   "ts": ts, "metric": metric, "fuel": fuel,
                   "value": float(value), "unit": unit or ""})
        inserted += 1

    db.session.commit()
    return jsonify({"inserted": inserted})


# ── Incidents ─────────────────────────────────────────────────────────────────

@osint_bp.route("/api/osint/incidents")
def osint_incidents():
    days  = _qint("days", 30)
    since = date.today() - timedelta(days=days)
    rows  = (
        OsintIncident.query
        .filter(OsintIncident.date >= since)
        .order_by(OsintIncident.date.desc().nullslast())
        .limit(1000)
        .all()
    )
    return jsonify([r.to_dict() for r in rows])


@osint_bp.route("/api/osint/incidents/ingest", methods=["POST"])
def osint_incidents_ingest():
    if not _ingest_auth_ok():
        return jsonify({"error": "unauthorized"}), 401

    data      = request.get_json(silent=True) or {}
    incidents = data.get("incidents", [])
    if not incidents:
        return jsonify({"error": "no incidents provided"}), 400

    upserted = 0
    now = datetime.now(timezone.utc)
    for inc in incidents:
        inc_id = inc.get("id")
        if not inc_id or not inc.get("source"):
            continue

        raw_date = inc.get("date")
        parsed_date = None
        if raw_date:
            try:
                parsed_date = date.fromisoformat(str(raw_date)[:10])
            except Exception:
                pass

        existing = OsintIncident.query.get(inc_id)
        if existing:
            existing.date        = parsed_date
            existing.state       = inc.get("state")
            existing.county      = inc.get("county")
            existing.operator    = inc.get("operator")
            existing.commodity   = inc.get("commodity")
            existing.lat         = inc.get("lat")
            existing.lng         = inc.get("lng")
            existing.fatalities  = int(inc.get("fatalities") or 0)
            existing.injuries    = int(inc.get("injuries") or 0)
            existing.cost_usd    = inc.get("cost_usd")
            existing.description = inc.get("description")
            existing.updated_at  = now
        else:
            db.session.add(OsintIncident(
                id=inc_id,
                source=inc["source"],
                source_id=inc.get("source_id"),
                type=inc.get("type"),
                date=parsed_date,
                state=inc.get("state"),
                county=inc.get("county"),
                operator=inc.get("operator"),
                commodity=inc.get("commodity"),
                lat=inc.get("lat"),
                lng=inc.get("lng"),
                fatalities=int(inc.get("fatalities") or 0),
                injuries=int(inc.get("injuries") or 0),
                cost_usd=inc.get("cost_usd"),
                description=inc.get("description"),
                metadata_json=json.dumps(inc.get("metadata") or {}),
                updated_at=now,
            ))
        upserted += 1

    db.session.commit()
    return jsonify({"upserted": upserted})


# ── ISO/RTO region overlay (electricityMaps balancing-authority polygons) ────

_regions_cache: bytes | None = None

# electricityMaps zone code → parent ISO/RTO for coloring
_ZONE_REGION: dict[str, str] = {
    # CAISO (California)
    "US-CAL-CISO": "CAISO", "US-CAL-BANC": "CAISO", "US-CAL-IID": "CAISO",
    "US-CAL-LDWP": "CAISO", "US-CAL-TIDC": "CAISO",
    # PJM
    "US-MIDA-PJM": "PJM",
    # MISO
    "US-MIDW-MISO": "MISO", "US-MIDW-AECI": "MISO", "US-MIDW-LGEE": "MISO",
    # ISO-NE
    "US-NE-ISNE": "ISO-NE",
    # NYISO
    "US-NY-NYIS": "NYISO",
    # SPP
    "US-CENT-SWPP": "SPP", "US-CENT-SPA": "SPP",
    # ERCOT
    "US-TEX-ERCO": "ERCOT",
    # SERC / Southeast (non-ISO)
    "US-CAR-CPLE": "SERC", "US-CAR-CPLW": "SERC", "US-CAR-DUK": "SERC",
    "US-CAR-SC": "SERC", "US-CAR-SCEG": "SERC",
    "US-FLA-FMPP": "SERC", "US-FLA-FPC": "SERC", "US-FLA-FPL": "SERC",
    "US-FLA-GVL": "SERC", "US-FLA-HST": "SERC", "US-FLA-JEA": "SERC",
    "US-FLA-SEC": "SERC", "US-FLA-TAL": "SERC", "US-FLA-TEC": "SERC",
    "US-SE-SOCO": "SERC", "US-TEN-TVA": "SERC",
    # WECC (Northwest + Southwest)
    "US-NW-AVA": "WECC", "US-NW-BPAT": "WECC", "US-NW-CHPD": "WECC",
    "US-NW-DOPD": "WECC", "US-NW-GCPD": "WECC", "US-NW-IPCO": "WECC",
    "US-NW-NEVP": "WECC", "US-NW-NWMT": "WECC", "US-NW-PACE": "WECC",
    "US-NW-PACW": "WECC", "US-NW-PGE": "WECC", "US-NW-PSCO": "WECC",
    "US-NW-PSEI": "WECC", "US-NW-SCL": "WECC", "US-NW-TPWR": "WECC",
    "US-NW-WACM": "WECC", "US-NW-WAUW": "WECC",
    "US-SW-AZPS": "WECC", "US-SW-EPE": "WECC", "US-SW-PNM": "WECC",
    "US-SW-SRP": "WECC", "US-SW-TEPC": "WECC", "US-SW-WALC": "WECC",
    # Alaska / Hawaii
    "US-AK": "Alaska", "US-AK-SEAPA": "Alaska",
    "US-HI": "Hawaii",
}

# electricityMaps geo/world.geojson — actual balancing-authority polygons
_EM_URL = (
    "https://raw.githubusercontent.com/electricitymaps/electricitymaps-contrib"
    "/master/geo/world.geojson"
)


@osint_bp.route("/api/osint/regions")
def osint_regions():
    global _regions_cache
    if _regions_cache is None:
        try:
            req = urllib.request.Request(
                _EM_URL,
                headers={"User-Agent": "cits-curator/1.0"},
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read())

            us_features = []
            for feat in data.get("features", []):
                props = feat.get("properties", {})
                zone  = props.get("zoneName", "")
                if not zone.startswith("US-"):
                    continue
                props["region"]   = _ZONE_REGION.get(zone, "Other")
                props["zoneName"] = zone
                us_features.append(feat)

            filtered = {"type": "FeatureCollection", "features": us_features}
            _regions_cache = json.dumps(filtered).encode()
        except Exception as exc:
            return jsonify({"error": str(exc)}), 502

    return Response(
        _regions_cache,
        mimetype="application/geo+json",
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ── News (reads curator Article table directly) ───────────────────────────────

@osint_bp.route("/api/osint/news")
def osint_news():
    limit = _qint("limit", 30, 100)
    rows  = (
        Article.query
        .order_by(Article.published_at.desc().nullslast(), Article.fetched_at.desc())
        .limit(limit)
        .all()
    )
    return jsonify([{
        "id":           a.id,
        "title":        a.title,
        "url":          a.url,
        "feed_name":    a.feed_name,
        "category":     a.category,
        "published_at": a.published_at.isoformat() if a.published_at else None,
    } for a in rows])
