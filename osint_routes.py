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
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any

from flask import Blueprint, jsonify, render_template, request
from sqlalchemy import func, text

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
    limit      = min(int(request.args.get("limit", "5000")), 25000)

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
    """Return the most recent fuel-mix snapshot for each ISO."""
    rows = db.session.execute(text("""
        SELECT g.iso, g.timestamp, g.metric, g.fuel, g.value, g.unit
        FROM osint_grid_snapshots g
        JOIN (
            SELECT iso, metric, fuel, MAX(timestamp) AS max_ts
            FROM osint_grid_snapshots
            GROUP BY iso, metric, fuel
        ) latest
          ON g.iso       = latest.iso
         AND g.metric    = latest.metric
         AND g.fuel      = latest.fuel
         AND g.timestamp = latest.max_ts
        ORDER BY g.iso, g.metric, g.fuel
    """)).fetchall()

    payload: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        ts = r.timestamp
        item = {
            "timestamp": ts.isoformat() if isinstance(ts, datetime) else str(ts),
            "metric":    r.metric,
            "fuel":      r.fuel,
            "value":     r.value,
            "unit":      r.unit,
        }
        payload.setdefault(r.iso, []).append(item)
    return jsonify(payload)


@osint_bp.route("/api/osint/grid/ingest", methods=["POST"])
def osint_grid_ingest():
    """Receive grid snapshot rows from the aggregator's push_grid.py GitHub Action."""
    if not _ingest_auth_ok():
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    rows = data.get("rows", [])
    if not rows:
        return jsonify({"inserted": 0})

    inserted = 0
    for row in rows:
        iso    = row.get("iso", "")
        metric = row.get("metric", "")
        fuel   = str(row.get("fuel") or "")
        value  = row.get("value")
        unit   = row.get("unit")

        if not iso or value is None:
            continue

        raw_ts = row.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            ts = datetime.utcnow()

        # Use raw SQL so we get portable upsert behaviour on both SQLite (dev)
        # and PostgreSQL (Render). The fuel column is NOT NULL so the unique
        # index always has a defined value to match against.
        db_url = db.engine.url.drivername
        if "postgresql" in db_url or "postgres" in db_url:
            db.session.execute(text("""
                INSERT INTO osint_grid_snapshots (iso, timestamp, metric, fuel, value, unit, metadata_json, created_at)
                VALUES (:iso, :ts, :metric, :fuel, :value, :unit, '{}', NOW())
                ON CONFLICT (iso, timestamp, metric, fuel) DO NOTHING
            """), {"iso": iso, "ts": ts, "metric": metric, "fuel": fuel,
                   "value": float(value), "unit": unit or ""})
        else:
            db.session.execute(text("""
                INSERT OR IGNORE INTO osint_grid_snapshots (iso, timestamp, metric, fuel, value, unit, metadata_json, created_at)
                VALUES (:iso, :ts, :metric, :fuel, :value, :unit, '{}', datetime('now'))
            """), {"iso": iso, "ts": ts, "metric": metric, "fuel": fuel,
                   "value": float(value), "unit": unit or ""})
        inserted += 1

    db.session.commit()
    return jsonify({"inserted": inserted})


# ── Incidents ─────────────────────────────────────────────────────────────────

@osint_bp.route("/api/osint/incidents")
def osint_incidents():
    days  = int(request.args.get("days", "30"))
    since = date.today() - timedelta(days=days)
    rows  = (
        OsintIncident.query
        .filter(
            (OsintIncident.date == None) | (OsintIncident.date >= since)  # noqa: E711
        )
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


# ── News (reads curator Article table directly) ───────────────────────────────

@osint_bp.route("/api/osint/news")
def osint_news():
    limit = min(int(request.args.get("limit", "30")), 100)
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
