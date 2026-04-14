import csv
import io
import os
import re
import html as html_lib
from datetime import datetime, timezone

import requests as req_lib
from flask import Blueprint, jsonify, render_template, request, Response
from app import db
from models import Article, RefreshLog, ResearchSession, ResearchArticle

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
            "week_key":       wk,
            "total":          total,
            "selected":       selected,
            "maybe":          maybe,
            "last_refreshed": latest_log.pushed_at.isoformat() if latest_log else None,
            "last_trigger":   latest_log.triggered_by if latest_log else None,
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
    week     = request.args.get("week", current_week_key())
    status   = request.args.get("status", "selected")
    fmt      = request.args.get("format", "text")

    statuses = [s.strip() for s in status.split(",")]
    articles = (
        Article.query
        .filter(Article.week_key == week, Article.status.in_(statuses))
        .order_by(Article.category, Article.feed_name)
        .all()
    )
    label = "-".join(statuses)

    if fmt == "text":
        lines = [f"CITS Newsletter — {week}", "=" * 48, ""]
        current_cat = None
        for a in articles:
            if a.category != current_cat:
                current_cat = a.category
                if lines[-1] != "":
                    lines.append("")
                lines.append(current_cat.upper())
                lines.append("-" * len(current_cat))
            lines.append(a.title)
            lines.append(a.url)
            lines.append(f"Source: {a.feed_name}")
            if a.curator_note:
                lines.append(f"Note: {a.curator_note}")
            if a.ai_summary:
                lines.append(f"Description: {a.ai_summary}")
            lines.append("")
        return Response(
            "\n".join(lines),
            mimetype="text/plain",
            headers={"Content-Disposition": f"attachment; filename=articles-{week}-{label}.txt"}
        )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["title", "url", "feed_name", "category", "published_at", "status", "curator_note", "description"])
    for a in articles:
        writer.writerow([
            a.title, a.url, a.feed_name, a.category,
            a.published_at.isoformat() if a.published_at else "",
            a.status, a.curator_note or "", a.ai_summary or ""
        ])
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=articles-{week}-{label}.csv"}
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


# ── Article description fetcher ───────────────────────────────────────────────

def fetch_article_description(url: str) -> str:
    """Pull meta description or first substantive paragraph — no AI needed."""
    try:
        resp = req_lib.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=8,
        )
        raw = resp.text

        # 1. <meta name="description"> — try both attribute orderings
        m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']{30,})["\']', raw, re.IGNORECASE)
        if not m:
            m = re.search(r'<meta[^>]+content=["\']([^"\']{30,})["\'][^>]+name=["\']description["\']', raw, re.IGNORECASE)

        # 2. <meta property="og:description">
        if not m:
            m = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']{30,})["\']', raw, re.IGNORECASE)
        if not m:
            m = re.search(r'<meta[^>]+content=["\']([^"\']{30,})["\'][^>]+property=["\']og:description["\']', raw, re.IGNORECASE)

        if m:
            return html_lib.unescape(m.group(1).strip())

        # 3. First substantive <p> tag as fallback
        paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', raw, re.DOTALL | re.IGNORECASE)
        for p in paragraphs:
            text = re.sub(r'<[^>]+>', '', p)
            text = html_lib.unescape(text).strip()
            text = re.sub(r'\s+', ' ', text)
            if len(text) > 100:
                return text[:300]

        return ""
    except Exception:
        return ""


@bp.route("/api/articles/<int:article_id>/summarize", methods=["POST"])
def summarize_article(article_id):
    article = Article.query.get_or_404(article_id)

    if article.ai_summary:
        return jsonify({"summary": article.ai_summary, "cached": True})

    description = fetch_article_description(article.url)

    if not description:
        return jsonify({"error": "No description found"}), 500

    article.ai_summary = description
    db.session.commit()
    return jsonify({"summary": description, "cached": False})


# ── Trigger aggregator refresh ───────────────────────────────────────────────

@bp.route("/api/trigger-refresh", methods=["POST"])
def trigger_refresh():
    data = request.get_json() or {}
    password = data.get("password", "")
    expected = os.environ.get("REFRESH_PASSWORD", "")

    if not expected:
        return jsonify({"error": "REFRESH_PASSWORD not configured"}), 500
    if password != expected:
        return jsonify({"error": "Invalid password"}), 403

    github_token = os.environ.get("GITHUB_PAT", "")
    if not github_token:
        return jsonify({"error": "GITHUB_PAT not configured"}), 500

    resp = req_lib.post(
        "https://api.github.com/repos/klemens-cc1/energy-security-aggregator/actions/workflows/curator-refresh.yml/dispatches",
        headers={
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={"ref": "main"},
        timeout=10,
    )

    if resp.status_code == 204:
        return jsonify({"status": "triggered", "message": "Refresh started — new articles will appear in ~2 minutes"})
    else:
        return jsonify({"error": f"GitHub API error {resp.status_code}: {resp.text}"}), 500


# ── Research page ─────────────────────────────────────────────────────────────

@bp.route("/research")
def research():
    return render_template("research.html")


# ── Research sessions API ──────────────────────────────────────────────────────

@bp.route("/api/research/sessions", methods=["GET"])
def list_research_sessions():
    sessions = (
        ResearchSession.query
        .order_by(ResearchSession.created_at.desc())
        .all()
    )
    result = []
    for s in sessions:
        d = s.to_dict()
        d["selected"] = sum(1 for a in s.articles if a.status == "selected")
        result.append(d)
    return jsonify(result)


@bp.route("/api/research/sessions", methods=["POST"])
def create_research_session():
    data = request.get_json() or {}
    topic = (data.get("topic") or "").strip()
    if not topic:
        return jsonify({"error": "topic is required"}), 400
    session = ResearchSession(topic=topic, owner=data.get("owner", "").strip() or None)
    db.session.add(session)
    db.session.commit()
    return jsonify(session.to_dict()), 201


@bp.route("/api/research/sessions/<int:session_id>", methods=["GET"])
def get_research_session(session_id):
    session = ResearchSession.query.get_or_404(session_id)
    d = session.to_dict()
    d["articles"] = [a.to_dict() for a in
                     sorted(session.articles, key=lambda a: (a.relevance_score or 0), reverse=True)]
    return jsonify(d)


@bp.route("/api/research/sessions/<int:session_id>", methods=["DELETE"])
def delete_research_session(session_id):
    session = ResearchSession.query.get_or_404(session_id)
    db.session.delete(session)
    db.session.commit()
    return jsonify({"deleted": session_id})


# ── Research article import ────────────────────────────────────────────────────

def score_article_for_topic(topic: str, title: str, description: str) -> int:
    """Score an article 1-10 for relevance to the given topic using Groq."""
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        return 5

    prompt = f"""You are a research assistant scoring articles for relevance to a policy research topic.

Topic: {topic}

Article title: {title}
Article description: {description}

Score this article's relevance to the topic from 1 to 10 using these guidelines:

HIGH score (7-10):
- Directly addresses the topic, key actors, or policy frameworks involved
- Contains substantive analysis, data, or policy developments related to the topic
- Written by a credible think tank, government body, academic, or specialist outlet

LOW score (1-4):
- Only tangentially mentions the topic
- Primarily about something else that happens to share a keyword
- Community news, events, or business/finance coverage unrelated to the policy dimension
- Opinion/editorial with no substantive policy content

Respond with ONLY a single integer from 1 to 10. No explanation."""

    try:
        resp = req_lib.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 5,
                "temperature": 0,
            },
            timeout=15,
        )
        text = resp.json()["choices"][0]["message"]["content"].strip()
        score = int(re.search(r"\d+", text).group())
        return max(1, min(10, score))
    except Exception:
        return 5


@bp.route("/api/research/sessions/<int:session_id>/import", methods=["POST"])
def import_research_urls(session_id):
    session = ResearchSession.query.get_or_404(session_id)
    data = request.get_json() or {}
    raw = data.get("urls", "")
    urls = [u.strip() for u in raw.splitlines() if u.strip().startswith("http")]

    if not urls:
        return jsonify({"error": "No valid URLs found"}), 400

    added = []
    skipped = 0
    for url in urls:
        existing = ResearchArticle.query.filter_by(session_id=session_id, url=url).first()
        if existing:
            skipped += 1
            continue

        title = ""
        description = fetch_article_description(url)

        # Try to extract title from the page
        try:
            resp = req_lib.get(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=8,
            )
            m = re.search(r'<title[^>]*>(.*?)</title>', resp.text, re.IGNORECASE | re.DOTALL)
            if m:
                title = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', m.group(1))).strip()
                title = html_lib.unescape(title)[:255]
        except Exception:
            pass

        score = score_article_for_topic(session.topic, title, description)

        article = ResearchArticle(
            session_id=session_id,
            url=url,
            title=title or url,
            description=description,
            relevance_score=score,
            status="unreviewed",
        )
        db.session.add(article)
        added.append(article)

    db.session.commit()
    return jsonify({
        "added": len(added),
        "skipped": skipped,
        "articles": [a.to_dict() for a in added],
    })


# ── Research article annotation ────────────────────────────────────────────────

@bp.route("/api/research/articles/<int:article_id>", methods=["PATCH"])
def update_research_article(article_id):
    article = ResearchArticle.query.get_or_404(article_id)
    data = request.get_json() or {}
    if "status" in data:
        article.status = data["status"]
    if "curator_note" in data:
        article.curator_note = data["curator_note"]
    db.session.commit()
    return jsonify(article.to_dict())


@bp.route("/api/research/articles/<int:article_id>", methods=["DELETE"])
def delete_research_article(article_id):
    article = ResearchArticle.query.get_or_404(article_id)
    db.session.delete(article)
    db.session.commit()
    return jsonify({"deleted": article_id})


# ── Research export ────────────────────────────────────────────────────────────

@bp.route("/api/research/sessions/<int:session_id>/export")
def export_research_session(session_id):
    session = ResearchSession.query.get_or_404(session_id)
    fmt = request.args.get("format", "markdown")
    status_filter = request.args.get("status", "selected")
    statuses = [s.strip() for s in status_filter.split(",")]

    articles = [a for a in session.articles if a.status in statuses]
    articles.sort(key=lambda a: (a.relevance_score or 0), reverse=True)

    safe_topic = re.sub(r'[^\w\s-]', '', session.topic)[:40].strip().replace(' ', '-').lower()

    if fmt == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["title", "url", "relevance_score", "status", "description", "curator_note"])
        for a in articles:
            writer.writerow([
                a.title or "", a.url, a.relevance_score or "",
                a.status, a.description or "", a.curator_note or "",
            ])
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename=research-{safe_topic}.csv"},
        )

    # Markdown / plain text research pack
    lines = [
        f"# Research Pack: {session.topic}",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        f"Articles: {len(articles)}",
        "",
        "---",
        "",
    ]
    for a in articles:
        lines.append(f"## {a.title or a.url}")
        lines.append(f"**Source:** {a.url}")
        if a.relevance_score:
            lines.append(f"**Relevance score:** {a.relevance_score}/10")
        if a.description:
            lines.append(f"**Description:** {a.description}")
        if a.curator_note:
            lines.append(f"**Note:** {a.curator_note}")
        lines.append("")

    ext = "md" if fmt == "markdown" else "txt"
    return Response(
        "\n".join(lines),
        mimetype="text/plain",
        headers={"Content-Disposition": f"attachment; filename=research-{safe_topic}.{ext}"},
    )


# ── Debug endpoints (remove after troubleshooting) ────────────────────────────

@bp.route("/api/debug/env")
def debug_env():
    key = os.environ.get("GROQ_API_KEY", "NOT SET")
    return jsonify({
        "key_set": key != "NOT SET",
        "key_prefix": key[:8] if key != "NOT SET" else "NOT SET",
        "key_length": len(key) if key != "NOT SET" else 0,
    })
