import csv
import io
import os
from datetime import datetime, timezone

from flask import Blueprint, jsonify, render_template, request, Response
from app import db
from models import Article, RefreshLog

bp = Blueprint("main", __name__)


def current_week_key():
    now = datetime.now(timezone.utc)
    return f"{now.year}-W{now.isocalendar()[1]:02d}"


# ── Main UI ───────────────────────────────────────────────────────────────────

@bp.route("/")
def index():
    weeks = (
        db.session.query(Article.week_key)
        .distinct()
        .order_by(Article.week_key.desc())
        .all()
    )
    week_keys = [w[0] for w in weeks]
    selected_week = request.args.get("week", week_keys[0] if week_keys else current_week_key())
    return render_template("index.html", weeks=week_keys, selected_week=selected_week)


@bp.route("/history")
def history():
    return render_template("history.html")


# ── Articles API ──────────────────────────────────────────────────────────────

@bp.route("/api/articles")
def get_articles():
    week   = request.args.get("week", current_week_key())
    cat    = request.args.get("category", "")
    source = request.args.get("source", "")
    status = request.args.get("status", "")
    search = request.args.get("search", "").strip()
    sort   = request.args.get("sort", "category")

    q = Article.query.filter_by(week_key=week)

    if cat:
        q = q.filter_by(category=cat)
    if source:
        q = q.filter_by(feed_name=source)
    if status:
        q = q.filter_by(status=status)
    if search:
        q = q.filter(Article.title.ilike(f"%{search}%"))

    if sort == "date":
        q = q.order_by(Article.published_at.desc().nullslast())
    elif sort == "source":
        q = q.order_by(Article.feed_name, Article.category)
    elif sort == "score":
        q = q.order_by(Article.ai_score.desc().nullslast())
    else:
        q = q.order_by(Article.category, Article.feed_name)

    return jsonify([a.to_dict() for a in q.all()])


@bp.route("/api/articles/<int:article_id>", methods=["PATCH"])
def update_article(article_id):
    article = Article.query.get_or_404(article_id)
    data = request.get_json()
    if "status" in data:
        article.status = data["status"]
    if "curator_note" in data:
        article.curator_note = data["curator_note"]
    db.session.commit()
    return jsonify(article.to_dict())


# ── Ingest endpoint (called by aggregator) ────────────────────────────────────

@bp.route("/api/ingest", methods=["POST"])
def ingest():
    api_key = request.headers.get("X-API-Key", "")
    if api_key != os.environ.get("INGEST_API_KEY", ""):
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json()
    articles     = data.get("articles", [])
    week_key     = data.get("week_key", current_week_key())
    triggered_by = data.get("triggered_by", "digest")

    added = 0
    skipped = 0
    for a in articles:
        if Article.query.filter_by(guid=a["guid"]).first():
            skipped += 1
            continue

        pub = None
        if a.get("published_at"):
            try:
                pub = datetime.fromisoformat(a["published_at"].replace("Z", "+00:00"))
            except Exception:
                pass

        db.session.add(Article(
            guid=a["guid"],
            title=a["title"],
            url=a["url"],
            feed_name=a["feed_name"],
            category=a.get("category", "General"),
            published_at=pub,
            week_key=week_key,
        ))
        added += 1

    # Log this refresh
    db.session.add(RefreshLog(
        week_key=week_key,
        articles_added=added,
        articles_skipped=skipped,
        triggered_by=triggered_by,
    ))

    db.session.commit()
    return jsonify({"added": added, "skipped": skipped, "week_key": week_key})


# ── Refresh log API ───────────────────────────────────────────────────────────

@bp.route("/api/refresh-log")
def refresh_log():
    limit = int(request.args.get("limit", 50))
    logs = (
        RefreshLog.query
        .order_by(RefreshLog.pushed_at.desc())
        .limit(limit)
        .all()
    )

    # Attach article totals per week for the history view
    result = []
    for log in logs:
        total = Article.query.filter_by(week_key=log.week_key).count()
        selected = Article.query.filter_by(week_key=log.week_key, status="selected").count()
        entry = log.to_dict()
        entry["total_articles"] = total
        entry["total_selected"] = selected
        result.append(entry)

    return jsonify(result)


@bp.route("/api/weeks")
def weeks():
    """All weeks that have articles, with summary stats."""
    week_rows = (
        db.session.query(Article.week_key)
        .distinct()
        .order_by(Article.week_key.desc())
        .all()
    )
    result = []
    for (wk,) in week_rows:
        total    = Article.query.filter_by(week_key=wk).count()
        selected = Article.query.filter_by(week_key=wk, status="selected").count()
        maybe    = Article.query.filter_by(week_key=wk, status="maybe").count()
        latest_log = (
            RefreshLog.query
            .filter_by(week_key=wk)
            .order_by(RefreshLog.pushed_at.desc())
            .first()
        )
        result.append({
            "week_key":      wk,
            "total":         total,
            "selected":      selected,
            "maybe":         maybe,
            "last_refreshed": latest_log.pushed_at.isoformat() if latest_log else None,
            "last_trigger":  latest_log.triggered_by if latest_log else None,
        })
    return jsonify(result)


# ── Stats API ─────────────────────────────────────────────────────────────────

@bp.route("/api/stats")
def stats():
    week = request.args.get("week", current_week_key())
    articles = Article.query.filter_by(week_key=week).all()

    by_category = {}
    by_source   = {}
    by_status   = {"unreviewed": 0, "selected": 0, "maybe": 0, "skip": 0}

    for a in articles:
        by_category[a.category] = by_category.get(a.category, 0) + 1
        by_source[a.feed_name]  = by_source.get(a.feed_name, 0) + 1
        by_status[a.status]     = by_status.get(a.status, 0) + 1

    return jsonify({
        "total":       len(articles),
        "by_category": by_category,
        "by_source":   by_source,
        "by_status":   by_status,
    })


# ── Export ────────────────────────────────────────────────────────────────────

@bp.route("/api/export")
def export():
    week   = request.args.get("week", current_week_key())
    status = request.args.get("status", "selected")
    fmt    = request.args.get("format", "csv")

    articles = (
        Article.query
        .filter_by(week_key=week, status=status)
        .order_by(Article.category, Article.feed_name)
        .all()
    )

    if fmt == "markdown":
        lines = [f"# Newsletter Articles — {week}\n"]
        current_cat = None
        for a in articles:
            if a.category != current_cat:
                current_cat = a.category
                lines.append(f"\n## {a.category}\n")
            note = f" — *{a.curator_note}*" if a.curator_note else ""
            lines.append(f"- [{a.title}]({a.url}) — {a.feed_name}{note}")
        return Response(
            "\n".join(lines),
            mimetype="text/markdown",
            headers={"Content-Disposition": f"attachment; filename=articles-{week}.md"}
        )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["title", "url", "feed_name", "category", "published_at", "status", "curator_note"])
    for a in articles:
        writer.writerow([
            a.title, a.url, a.feed_name, a.category,
            a.published_at.isoformat() if a.published_at else "",
            a.status, a.curator_note or ""
        ])
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=articles-{week}.csv"}
    )


# ── Filter dropdowns ──────────────────────────────────────────────────────────

@bp.route("/api/filters")
def filters():
    week = request.args.get("week", current_week_key())
    cats = (
        db.session.query(Article.category)
        .filter_by(week_key=week)
        .distinct()
        .order_by(Article.category)
        .all()
    )
    sources = (
        db.session.query(Article.feed_name)
        .filter_by(week_key=week)
        .distinct()
        .order_by(Article.feed_name)
        .all()
    )
    return jsonify({
        "categories": [c[0] for c in cats],
        "sources":    [s[0] for s in sources],
    })
