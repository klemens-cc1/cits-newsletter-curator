import csv
import io
import os
import re
import html as html_lib
import threading
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

import feedparser as fp_lib
import requests as req_lib
from flask import Blueprint, jsonify, render_template, request, Response
from app import db
from models import Article, RefreshLog, ResearchSession, ResearchArticle, FeedSource, ResearchJob, Feedback

bp = Blueprint("main", __name__)


@dataclass
class SearchOptions:
    topic: str
    date_days: int | None = None        # None = all time; else last N days
    date_from: str = ""                 # ISO "YYYY-MM-DD"; custom range start
    date_to: str = ""                   # ISO "YYYY-MM-DD"; custom range end
    min_score: int = 1                  # discard articles scoring below this
    max_results: int = 50               # cap total articles imported
    english_only: bool = False          # skip non-English articles
    must_include: list = field(default_factory=list)   # all terms must appear in title+desc
    must_exclude: list = field(default_factory=list)   # any match skips the article
    source_types: list = field(default_factory=list)   # empty = all types


def current_week_key():
    now = datetime.now(timezone.utc)
    return f"{now.year}-W{now.isocalendar()[1]:02d}"


# ── Main UI ───────────────────────────────────────────────────────────────────

@bp.route("/")
def home():
    return render_template("home.html")


@bp.route("/newsletter")
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


# ── Stats / Feedback / Admin ──────────────────────────────────────────────────

@bp.route("/api/home-stats")
def api_home_stats():
    total_newsletter = Article.query.count()
    total_sessions   = ResearchSession.query.count()
    total_selected   = ResearchArticle.query.filter_by(status="selected").count()
    last_log         = RefreshLog.query.order_by(RefreshLog.pushed_at.desc()).first()
    last_refresh     = last_log.pushed_at.isoformat() if last_log and last_log.pushed_at else None
    return jsonify({
        "total_newsletter_articles": total_newsletter,
        "total_research_sessions":   total_sessions,
        "total_research_selected":   total_selected,
        "last_refresh":              last_refresh,
    })


@bp.route("/api/feedback", methods=["POST"])
def api_feedback():
    data    = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()

    if not message:
        return jsonify({"error": "Message is required."}), 400

    fb = Feedback(message=message)
    db.session.add(fb)
    db.session.commit()
    return jsonify({"ok": True}), 200


@bp.route("/admin/feedback")
def admin_feedback():
    expected_pw = os.environ.get("ADMIN_PASSWORD", "")
    pw = request.args.get("pw", "")
    if not expected_pw or pw != expected_pw:
        return Response("Unauthorized.", 403)
    entries = Feedback.query.order_by(Feedback.submitted_at.desc()).all()
    rows = "".join(
        f'<tr><td style="color:#909090;white-space:nowrap;padding:10px 16px 10px 0;font-size:12px;font-family:\'Oswald\',sans-serif;vertical-align:top">{e.submitted_at.strftime("%Y-%m-%d %H:%M") if e.submitted_at else ""}</td>'
        f'<td style="padding:10px 0;font-size:14px;font-family:\'Merriweather\',serif;line-height:1.6">{html_lib.escape(e.message)}</td></tr>'
        for e in entries
    )
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<link href="https://fonts.googleapis.com/css2?family=Oswald:wght@400;500&family=Merriweather:wght@300;400&display=swap" rel="stylesheet">
<title>Feedback — CITS Admin</title>
<style>
  body{{font-family:'Merriweather',serif;background:#efefef;color:#252525;padding:40px 48px;}}
  h1{{font-family:'Oswald',sans-serif;font-size:22px;letter-spacing:3px;text-transform:uppercase;margin-bottom:6px;}}
  .underline{{width:40px;height:3px;background:#ba0c2f;margin-bottom:32px;}}
  table{{border-collapse:collapse;width:100%;max-width:860px;}}
  tr{{border-bottom:1px solid #e0e0e0;}}
</style></head><body>
<h1>Feedback</h1><div class="underline"></div>
<p style="font-size:13px;color:#909090;margin-bottom:24px;font-family:'Oswald',sans-serif;letter-spacing:1px">{len(entries)} SUBMISSION{"S" if len(entries) != 1 else ""}</p>
<table>{rows if rows else '<tr><td style="padding:20px 0;color:#909090">No feedback yet.</td></tr>'}</table>
</body></html>"""


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


# ── Research export summaries ────────────────────────────────────────────────

@bp.route("/api/research/sessions/<int:session_id>/export_summaries", methods=["POST"])
def export_summaries(session_id):
    """Generate ≤50-word summaries for a batch of articles for export use.

    Uses llama-3.1-8b-instant (fast, lightweight) so these calls don't compete
    with the main search/score pipeline which uses the 70b model.
    """
    ResearchSession.query.get_or_404(session_id)
    data = request.get_json() or {}
    article_ids = data.get("article_ids", [])

    if not article_ids:
        return jsonify({"summaries": {}})

    articles = ResearchArticle.query.filter(
        ResearchArticle.session_id == session_id,
        ResearchArticle.id.in_(article_ids),
    ).all()

    groq_key = os.environ.get("GROQ_API_KEY", "")
    summaries = {}

    for article in articles:
        context = (article.description or "").strip()
        aid = str(article.id)

        if not context:
            summaries[aid] = ""
            continue

        # Fallback when Groq is unavailable: truncate description at word boundary
        if not groq_key:
            words = context.split()
            summaries[aid] = " ".join(words[:50]) + ("…" if len(words) > 50 else "")
            continue

        prompt = (
            "Summarize the following article excerpt in no more than 50 words. "
            "State what happened or what was found — be direct and factual. "
            "Do not start with 'This article' or any preamble. No markdown.\n\n"
            f"{context[:600]}"
        )
        try:
            resp = req_lib.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 80,
                    "temperature": 0.15,
                },
                timeout=10,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
            # Hard-enforce the 50-word cap in case the model runs long
            words = text.split()
            if len(words) > 50:
                text = " ".join(words[:50]) + "…"
            summaries[aid] = text
        except Exception:
            words = context.split()
            summaries[aid] = " ".join(words[:50]) + ("…" if len(words) > 50 else "")

    return jsonify({"summaries": summaries})


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

    if fmt == "text":
        # Clean plain text — no markdown syntax, easy to paste into Word/Docs
        text_lines = [
            f"RESEARCH PACK: {session.topic.upper()}",
            f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
            f"Articles: {len(articles)}",
            "",
            "=" * 72,
            "",
        ]
        for a in articles:
            text_lines.append(a.title or a.url)
            text_lines.append(a.url)
            if a.relevance_score:
                text_lines.append(f"Relevance: {a.relevance_score}/10")
            if a.description:
                text_lines.append(f"Summary: {a.description}")
            if a.curator_note:
                text_lines.append(f"Note: {a.curator_note}")
            text_lines.append("")
            text_lines.append("-" * 48)
            text_lines.append("")
        return Response(
            "\n".join(text_lines),
            mimetype="text/plain",
            headers={"Content-Disposition": f"attachment; filename=research-{safe_topic}.txt"},
        )

    ext = "md" if fmt == "markdown" else "txt"
    return Response(
        "\n".join(lines),
        mimetype="text/plain",
        headers={"Content-Disposition": f"attachment; filename=research-{safe_topic}.{ext}"},
    )


# ── Automated search pipeline ─────────────────────────────────────────────────

def generate_query_variations(topic: str) -> list[str]:
    """Use Groq to generate up to 4 focused search query strings for the topic."""
    groq_key = os.environ.get("GROQ_API_KEY", "")
    if not groq_key:
        return [topic]

    prompt = f"""Generate 4 short search queries (3-6 words each) for finding policy research articles about:
"{topic}"

Return ONLY the 4 queries, one per line. No numbering, no explanation, no quotes."""

    try:
        resp = req_lib.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 120,
                "temperature": 0.3,
            },
            timeout=15,
        )
        lines = resp.json()["choices"][0]["message"]["content"].strip().splitlines()
        queries = [l.strip().strip('"').strip("'") for l in lines if l.strip()][:4]
        if topic not in queries:
            queries.insert(0, topic)
        return queries[:5]
    except Exception:
        return [topic]


def resolve_url(url: str) -> str:
    """Return the real article URL, resolving wrappers where possible.

    Google News blobs are now server-side encrypted — base64 decode no longer
    works and the viewer API returns 400. We keep this function as a no-op for
    Google News URLs so callers don't need to change; the real source name is
    extracted from the RSS title suffix in _import_single_article and on the
    frontend.
    """
    return url


def _parse_site_name(raw_html: str) -> str:
    """Extract og:site_name from page HTML — the proper publication/site name."""
    for pat in [
        r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:site_name["\']',
    ]:
        m = re.search(pat, raw_html, re.IGNORECASE)
        if m:
            return html_lib.unescape(m.group(1).strip())
    return ''


def _doi_from_url(url: str) -> str:
    """Extract a DOI (10.XXXX/...) from a doi.org URL or ?doi= param."""
    m = re.search(r'(?:doi\.org/|[?&]doi=)(10\.\d{4,}/[^\s?#&"\']+)', url, re.IGNORECASE)
    return m.group(1) if m else ''


def _crossref_meta(doi: str) -> tuple[datetime | None, str]:
    """Return (publication_date, journal_name) from Crossref for a DOI.

    Uses the polite-pool endpoint (no API key required; just a mailto header).
    Returns (None, '') on any error.
    """
    try:
        encoded = urllib.parse.quote(doi, safe='/')
        resp = req_lib.get(
            f"https://api.crossref.org/works/{encoded}",
            headers={"User-Agent": "CITS-Research-Curator/1.0 (mailto:research@cits.uga.edu)"},
            timeout=8,
        )
        if resp.status_code != 200:
            return None, ''
        msg = resp.json().get('message', {})

        # Journal / container title — prefer short-container-title if present
        titles = msg.get('container-title') or []
        short  = msg.get('short-container-title') or []
        journal = (short[0] if short else '') or (titles[0] if titles else '') or (msg.get('publisher') or '')

        # Publication date — iterate fields in order of specificity
        pub_dt = None
        for field in ('published', 'published-print', 'published-online', 'created'):
            parts = (msg.get(field) or {}).get('date-parts', [[]])[0]
            if parts and parts[0]:
                try:
                    year  = int(parts[0])
                    month = int(parts[1]) if len(parts) > 1 else 1
                    day   = int(parts[2]) if len(parts) > 2 else 1
                    pub_dt = datetime(year, month, day, tzinfo=timezone.utc)
                    break
                except (ValueError, TypeError):
                    continue

        return pub_dt, journal.strip()
    except Exception:
        return None, ''


def _parse_pub_date(raw_html: str) -> datetime | None:
    """Extract article:published_time or datePublished from page HTML."""
    for pat in [
        r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']article:published_time["\']',
        r'"datePublished"\s*:\s*"([^"]{10,30})"',
    ]:
        m = re.search(pat, raw_html, re.IGNORECASE)
        if m:
            try:
                return datetime.fromisoformat(m.group(1)[:19]).replace(tzinfo=timezone.utc)
            except Exception:
                continue
    return None


def _pub_str(parsed_time) -> str:
    """Convert feedparser time_struct to ISO string."""
    if not parsed_time:
        return ""
    try:
        return datetime(*parsed_time[:6], tzinfo=timezone.utc).isoformat()
    except Exception:
        return ""


def _is_english(text: str) -> bool:
    """Return True if text appears to be English. Defaults True when uncertain."""
    if not text or len(text.split()) < 5:
        return True   # too short to detect reliably
    try:
        from langdetect import detect
        return detect(text) == 'en'
    except Exception:
        return True   # include on error rather than silently drop articles


def _domain_from_url(url: str) -> str:
    """Return hostname without leading www."""
    try:
        h = urllib.parse.urlparse(url).hostname or ''
        return h[4:] if h.startswith('www.') else h
    except Exception:
        return ''


def _google_source_fields(entry) -> tuple[str, str]:
    """Extract (source_name, source_domain) from a feedparser Google News entry.

    Google News RSS items carry <source url="https://publisher.com">Publisher</source>.
    feedparser exposes this as entry.source = {'value': 'Publisher', 'href': 'https://...'}
    """
    src = getattr(entry, 'source', None) or {}
    if isinstance(src, dict):
        name = src.get('value') or src.get('name') or ''
        href = src.get('href') or ''
    else:
        name = getattr(src, 'value', '') or ''
        href = getattr(src, 'href', '') or ''
    domain = _domain_from_url(href) if href else ''
    return name.strip(), domain.strip()


def search_google_news(query: str, date_days: int | None = None) -> list[dict]:
    """Fetch up to 25 results from Google News RSS for a query."""
    if date_days:
        from_date = (datetime.now(timezone.utc) - timedelta(days=date_days)).strftime('%Y-%m-%d')
        query = f"{query} after:{from_date}"
    encoded = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
    try:
        parsed = fp_lib.parse(url)
        results = []
        for entry in parsed.entries[:25]:
            link = getattr(entry, "link", "") or ""
            title = getattr(entry, "title", "") or ""
            source_name, source_domain = _google_source_fields(entry)
            # Guarantee title ends with ' - Source Name' so sourceOf() can display it.
            # Google News RSS already includes it, but make explicit in case it's absent.
            if source_name and not re.search(r'\s+-\s+\S', title[-50:]):
                title = f"{title} - {source_name}"
            if link:
                results.append({
                    "url": link,
                    "title": title,
                    "source": "google_news",
                    "published_at": _pub_str(getattr(entry, "published_parsed", None)),
                    "source_name": source_name,
                    "source_domain": source_domain,
                })
        return results
    except Exception:
        return []


def search_yahoo_news(query: str) -> list[dict]:
    """Fetch up to 25 results from Yahoo News RSS for a query."""
    encoded = urllib.parse.quote(query)
    url = f"https://news.search.yahoo.com/search?p={encoded}&output=rss"
    try:
        parsed = fp_lib.parse(url)
        results = []
        for entry in parsed.entries[:25]:
            link = getattr(entry, "link", "") or ""
            title = getattr(entry, "title", "") or ""
            if link:
                results.append({
                    "url": link, "title": title, "source": "yahoo_news",
                    "published_at": _pub_str(getattr(entry, "published_parsed", None)),
                })
        return results
    except Exception:
        return []


def search_gdelt(query: str, date_days: int | None = None) -> list[dict]:
    """Query GDELT DOC API for matching articles (up to 50)."""
    encoded = urllib.parse.quote(query)
    url = (
        f"https://api.gdeltproject.org/api/v2/doc/doc"
        f"?query={encoded}&mode=artlist&maxrecords=50&format=json"
    )
    if date_days:
        start = (datetime.now(timezone.utc) - timedelta(days=date_days)).strftime('%Y%m%d%H%M%S')
        url += f"&startdatetime={start}"
    try:
        resp = req_lib.get(url, timeout=25)
        data = resp.json()
        results = []
        for article in data.get("articles", []):
            link = article.get("url", "")
            title = article.get("title", "")
            pub_str = ""
            seendate = article.get("seendate", "")
            if seendate:
                try:
                    pub_str = datetime.strptime(seendate, '%Y%m%dT%H%M%SZ').replace(
                        tzinfo=timezone.utc).isoformat()
                except Exception:
                    pass
            if link:
                results.append({"url": link, "title": title, "source": "gdelt",
                                 "published_at": pub_str})
        return results
    except Exception:
        return []


def search_feeds_by_topic(
    topic: str, keywords: list[str], date_days: int | None = None
) -> list[dict]:
    """Scan use_research=True feeds from feed_sources for entries matching any keyword."""
    try:
        feeds = FeedSource.query.filter_by(use_research=True, active=True).all()
    except Exception:
        return []

    results = []
    kw_lower = [k.lower() for k in keywords if len(k) > 3]
    if not kw_lower:
        kw_lower = [topic.lower()]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=date_days)) if date_days else None

    for feed in feeds:
        try:
            parsed = fp_lib.parse(feed.url, agent="cits-newsletter-curator/1.0")
            for entry in parsed.entries[:30]:
                pub_t = getattr(entry, "published_parsed", None)
                if cutoff and pub_t:
                    if datetime(*pub_t[:6], tzinfo=timezone.utc) < cutoff:
                        continue
                title = getattr(entry, "title", "") or ""
                summary = getattr(entry, "summary", "") or ""
                combined = (title + " " + summary).lower()
                if any(kw in combined for kw in kw_lower):
                    link = getattr(entry, "link", "")
                    if link:
                        results.append({
                            "url": link,
                            "title": title,
                            "source": f"feed:{feed.name}",
                            "published_at": _pub_str(pub_t),
                            "source_name": feed.name,
                        })
        except Exception:
            continue

    return results


def search_semantic_scholar(query: str, date_days: int | None = None,
                            date_from: str = "", date_to: str = "") -> list[dict]:
    """Search Semantic Scholar (220M+ papers) via their Graph API."""
    params: dict = {
        'query': query,
        'fields': 'title,abstract,year,externalIds,openAccessPdf,citationCount,publicationDate,journal,venue',
        'limit': 25,
    }
    # Year-range filter — prefer explicit date_from/date_to, fall back to date_days
    now_year = datetime.now(timezone.utc).year
    if date_from or date_to:
        yr_from = date_from[:4] if date_from else ''
        yr_to   = date_to[:4]   if date_to   else str(now_year)
        if yr_from:
            params['year'] = f"{yr_from}-{yr_to}"
    elif date_days:
        year_cutoff = (datetime.now(timezone.utc) - timedelta(days=date_days)).year
        params['year'] = f"{year_cutoff}-{now_year}"

    headers: dict = {}
    api_key = os.environ.get('SEMANTIC_SCHOLAR_API_KEY', '')
    if api_key:
        headers['x-api-key'] = api_key

    try:
        resp = req_lib.get(
            'https://api.semanticscholar.org/graph/v1/paper/search',
            params=params,
            headers=headers,
            timeout=20,
        )
        resp.raise_for_status()
        papers = resp.json().get('data', [])
        results = []
        cutoff = (datetime.now(timezone.utc) - timedelta(days=date_days)) if date_days else None

        for paper in papers:
            ext_ids    = paper.get('externalIds') or {}
            oa_pdf     = (paper.get('openAccessPdf') or {}).get('url', '')
            doi        = ext_ids.get('DOI', '')
            arxiv_id   = ext_ids.get('ArXiv', '')
            paper_id   = paper.get('paperId', '')

            # URL priority: open-access PDF > DOI > arXiv abs page > S2 page
            if oa_pdf:
                url = oa_pdf
            elif doi:
                url = f'https://doi.org/{doi}'
            elif arxiv_id:
                url = f'https://arxiv.org/abs/{arxiv_id}'
            elif paper_id:
                url = f'https://www.semanticscholar.org/paper/{paper_id}'
            else:
                continue

            title_raw = (paper.get('title') or '').strip()
            abstract  = re.sub(r'\s+', ' ', (paper.get('abstract') or '').strip())[:480]

            # Append citation count if meaningful — useful signal for policy researchers
            cite_n = paper.get('citationCount') or 0
            if cite_n >= 5:
                abstract = f"{abstract} [{cite_n} citations]".strip()

            pub_date = paper.get('publicationDate') or ''
            year     = paper.get('year')
            pub_str  = ''
            if pub_date:
                try:
                    pub_str = datetime.strptime(pub_date[:10], '%Y-%m-%d').replace(
                        tzinfo=timezone.utc).isoformat()
                except Exception:
                    pass
            elif year:
                pub_str = f'{year}-01-01T00:00:00+00:00'

            # Sub-year precision cutoff check
            if cutoff and pub_str:
                try:
                    if datetime.fromisoformat(pub_str) < cutoff:
                        continue
                except Exception:
                    pass

            # Use actual journal/venue name when available; fall back to S2 label
            journal_info = paper.get('journal') or {}
            venue        = paper.get('venue') or ''
            journal_name = (journal_info.get('name') or '').strip() or venue.strip() or 'Semantic Scholar'

            if title_raw:
                results.append({
                    'url':          url,
                    'title':        title_raw,
                    'description':  abstract,
                    'source':       'semantic_scholar',
                    'source_name':  journal_name,
                    'published_at': pub_str,
                })
        return results
    except Exception:
        return []


def search_arxiv(query: str, date_days: int | None = None) -> list[dict]:
    """Search arXiv preprint server via its Atom API."""
    # Only encode the query text — keep 'all:' literal so arXiv parses it correctly
    encoded_q = urllib.parse.quote(query)
    url = (
        f"https://export.arxiv.org/api/query"
        f"?search_query=all:{encoded_q}&start=0&max_results=25&sortBy=relevance"
    )
    try:
        # Fetch with requests for reliable redirect handling, then parse with feedparser
        resp = req_lib.get(url, timeout=20, headers={'User-Agent': 'cits-curator/1.0'})
        resp.raise_for_status()
        feed = fp_lib.parse(resp.content)
        results = []
        cutoff = (datetime.now(timezone.utc) - timedelta(days=date_days)) if date_days else None
        for entry in feed.entries:
            link = getattr(entry, 'id', '') or ''
            link = link.replace('http://arxiv.org/', 'https://arxiv.org/')
            title_raw = (getattr(entry, 'title', '') or '').replace('\n', ' ').strip()
            summary = (getattr(entry, 'summary', '') or '').replace('\n', ' ').strip()
            summary = re.sub(r'\s+', ' ', summary)[:500]
            pub_t = getattr(entry, 'published_parsed', None)
            pub_str = _pub_str(pub_t)
            if cutoff and pub_t:
                try:
                    if datetime(*pub_t[:6], tzinfo=timezone.utc) < cutoff:
                        continue
                except Exception:
                    pass
            if link:
                results.append({
                    'url': link,
                    'title': title_raw,
                    'description': summary,
                    'source': 'arxiv',
                    'source_name': 'arXiv',
                    'published_at': pub_str,
                })
        return results
    except Exception:
        return []


def search_osti(query: str, date_days: int | None = None,
               date_from: str = "", date_to: str = "") -> list[dict]:
    """Search OSTI.gov (US Dept of Energy) publications via their JSON API."""
    params: dict = {
        'q': query,
        'rows': 25,
    }
    if date_from:
        params['date_range_start'] = date_from[:10]
        if date_to:
            params['date_range_end'] = date_to[:10]
    elif date_days:
        params['date_range_start'] = (
            datetime.now(timezone.utc) - timedelta(days=date_days)
        ).strftime('%Y-%m-%d')
    try:
        resp = req_lib.get(
            'https://www.osti.gov/api/v1/records',
            params=params,
            headers={'Accept': 'application/json'},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        # OSTI may return a bare list or wrap records in a dict
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            # Try common wrapper keys
            records = (data.get('records') or data.get('data') or
                       data.get('list') or data.get('results') or [])
        else:
            return []
        results = []
        for rec in records:
            doi = (rec.get('doi') or '').strip()
            osti_id = str(rec.get('osti_id') or '').strip()
            article_url = f'https://doi.org/{doi}' if doi else (
                f'https://www.osti.gov/biblio/{osti_id}' if osti_id else ''
            )
            if not article_url:
                continue
            title_raw = (rec.get('title') or '').strip()
            # OSTI uses 'description' for abstract in Dublin Core schema
            abstract = re.sub(r'\s+', ' ',
                              (rec.get('description') or rec.get('abstract') or '').strip())[:500]
            pub_date = (rec.get('publication_date') or '')[:10]
            pub_str = ''
            if pub_date:
                try:
                    pub_str = datetime.strptime(pub_date, '%Y-%m-%d').replace(
                        tzinfo=timezone.utc).isoformat()
                except Exception:
                    pass
            # Prefer the actual journal name; fall back to "OSTI.gov" as the repository
            osti_journal = (
                (rec.get('journal_name') or '').strip() or
                (rec.get('publisher') or '').strip() or
                'OSTI.gov'
            )

            if title_raw:
                results.append({
                    'url': article_url,
                    'title': title_raw,
                    'description': abstract,
                    'source': 'osti',
                    'source_name': osti_journal,
                    'published_at': pub_str,
                })
        return results
    except Exception:
        return []


def _import_single_article(
    session_id: int, url: str, title: str, topic: str, seen_urls: set,
    min_score: int = 1, published_at: str = "", source_name: str = "",
    must_include: list = None, must_exclude: list = None, english_only: bool = False,
    pre_description: str = "", source_domain: str = "",
) -> dict | None:
    """Resolve URL, fetch page, score, and insert one research article."""
    url = resolve_url(url)

    if url in seen_urls:
        return None
    seen_urls.add(url)

    if ResearchArticle.query.filter_by(session_id=session_id, url=url).first():
        return None

    description = pre_description
    pub_dt: datetime | None = None

    # Use passed-in date if available (from feedparser / GDELT / arXiv / OSTI)
    if published_at:
        try:
            pub_dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except Exception:
            pass

    # Skip page fetch for Google News wrapper URLs — their pages only return
    # boilerplate ("Comprehensive up-to-date news coverage...") and the real
    # article URL cannot be recovered server-side (blob encoding is encrypted).
    # Title and published_at are already available from the RSS feed.
    is_gnews = 'news.google.com' in url

    # Ensure Google News titles carry ' - Source Name' suffix so the frontend
    # sourceOf() function can display the real publisher instead of news.google.com.
    if is_gnews and source_name and title and not re.search(r'\s+-\s+\S', title[-50:]):
        title = f"{title} - {source_name}"

    # Skip page fetch when the caller already supplied a description (e.g. arXiv
    # abstract, OSTI abstract) — we have everything we need from the API.
    if not is_gnews and not pre_description:
        try:
            resp = req_lib.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml",
                },
                timeout=10,
            )
            raw = resp.text
            url = resp.url  # capture final URL after any further redirects

            # Title
            if not title or title == url:
                m = re.search(r'<title[^>]*>(.*?)</title>', raw, re.IGNORECASE | re.DOTALL)
                if m:
                    title = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', m.group(1))).strip()
                    title = html_lib.unescape(title)[:255]

            # Description
            for pat in [
                r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']{30,})["\']',
                r'<meta[^>]+content=["\']([^"\']{30,})["\'][^>]+name=["\']description["\']',
                r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']{30,})["\']',
                r'<meta[^>]+content=["\']([^"\']{30,})["\'][^>]+property=["\']og:description["\']',
            ]:
                m = re.search(pat, raw, re.IGNORECASE)
                if m:
                    description = html_lib.unescape(m.group(1).strip())
                    break

            if not description:
                for p in re.findall(r'<p[^>]*>(.*?)</p>', raw, re.DOTALL | re.IGNORECASE):
                    text = re.sub(r'\s+', ' ', html_lib.unescape(re.sub(r'<[^>]+>', '', p))).strip()
                    if len(text) > 100:
                        description = text[:300]
                        break

            # Published date (only if not already set from feed)
            if not pub_dt:
                pub_dt = _parse_pub_date(raw)

            # Site name from og:site_name (only if not already known from feed/API)
            if not source_name:
                source_name = _parse_site_name(raw)

        except Exception:
            pass

    # Crossref lookup for DOI URLs — authoritative journal name + exact pub date.
    # Runs for: doi.org links, S2/OSTI articles with generic source names.
    # Skipped for regular news (no DOI in URL) to avoid adding latency.
    doi = _doi_from_url(url)
    if doi and (not pub_dt or source_name in ('', 'Semantic Scholar', 'OSTI.gov', None)):
        cr_dt, cr_journal = _crossref_meta(doi)
        if cr_dt and not pub_dt:
            pub_dt = cr_dt
        if cr_journal and source_name in ('', 'Semantic Scholar', 'OSTI.gov', None):
            source_name = cr_journal

    # ── Keyword filters ───────────────────────────────────────────────────────
    # Checked before scoring (cheaper than the Groq API call).
    haystack = f"{title} {description}".lower()
    if must_include:
        if not all(t.lower() in haystack for t in must_include if t):
            return None
    if must_exclude:
        if any(t.lower() in haystack for t in must_exclude if t):
            return None

    # ── Language filter ────────────────────────────────────────────────────────
    if english_only and not _is_english(f"{title} {description}"):
        return None

    score = score_article_for_topic(topic, title or url, description)

    if score < min_score:
        return None

    article = ResearchArticle(
        session_id=session_id,
        url=url,
        title=title or url,
        description=description,
        relevance_score=score,
        published_at=pub_dt,
        source_name=source_name or None,
        source_domain=source_domain or _domain_from_url(url) or None,
        status="unreviewed",
    )
    db.session.add(article)
    return article.to_dict()


def run_research_search(app, job_id: int, session_id: int, topic: str, opts: SearchOptions | None = None):
    """Background thread: 6-phase automated search and import pipeline."""
    if opts is None:
        opts = SearchOptions(topic=topic)

    with app.app_context():

        def update_job(phase_num, phase, urls_found=None, status="running"):
            job = ResearchJob.query.get(job_id)
            if job:
                job.phase_num = phase_num
                job.phase = phase
                job.status = status
                if urls_found is not None:
                    job.urls_found = urls_found
                db.session.commit()

        def fail_job(error_msg):
            job = ResearchJob.query.get(job_id)
            if job:
                job.status = "error"
                job.error = error_msg[:500]
                job.completed_at = datetime.now(timezone.utc)
                db.session.commit()

        try:
            session = ResearchSession.query.get(session_id)
            if not session:
                fail_job("Session not found")
                return

            all_candidates = []

            # Phase 1 — generate query variations
            update_job(1, "Generating search queries…")
            queries = generate_query_variations(topic)
            keywords = [w for w in topic.split() if len(w) > 3] or topic.split()

            # Compute effective date_days for functions that only support a lookback window.
            # When a custom date_from is set, derive days-since as an approximation.
            eff_days = opts.date_days
            if not eff_days and opts.date_from:
                try:
                    from_dt = datetime.strptime(opts.date_from, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                    eff_days = max(1, (datetime.now(timezone.utc) - from_dt).days)
                except Exception:
                    pass

            # Phase 2 — Google News RSS
            update_job(2, f"Searching Google News ({len(queries)} queries)…")
            for q in queries:
                all_candidates.extend(search_google_news(q, eff_days))

            # Phase 3 — Yahoo News RSS
            update_job(3, "Searching Yahoo News…")
            all_candidates.extend(search_yahoo_news(topic))

            # Phase 4 — GDELT
            update_job(4, "Querying GDELT archive…")
            all_candidates.extend(search_gdelt(topic, eff_days))

            # Phase 5 — Specialist feeds
            update_job(5, "Scanning specialist RSS feeds…")
            all_candidates.extend(search_feeds_by_topic(topic, keywords, eff_days))

            # Phase 6 — Semantic Scholar (supports full date_from/date_to range)
            update_job(6, "Searching Semantic Scholar…")
            for q in queries[:2]:
                all_candidates.extend(search_semantic_scholar(
                    q, eff_days, opts.date_from, opts.date_to))

            # Phase 7 — OSTI (supports full date_from/date_to range)
            update_job(7, "Searching OSTI.gov (DOE research)…")
            all_candidates.extend(search_osti(topic, eff_days, opts.date_from, opts.date_to))

            # Deduplicate
            seen: set[str] = set()
            unique_candidates = []
            for c in all_candidates:
                url = c["url"]
                if url not in seen and url.startswith("http"):
                    seen.add(url)
                    unique_candidates.append(c)

            update_job(7, "Searching OSTI.gov (DOE research)…", urls_found=len(unique_candidates))

            # Phase 8 — Score and import (filtered by min_score, capped at max_results)
            update_job(8, f"Scoring {len(unique_candidates)} articles…",
                       urls_found=len(unique_candidates))

            # Build feed→type cache once so Phase 6 doesn't hit the DB per article
            feed_type_cache: dict[str, str] = {}
            if opts.source_types:
                for feed in FeedSource.query.filter_by(active=True).all():
                    tags = [t.strip().lower() for t in (feed.tags or '').split(',')]
                    if any(t in ('think_tank', 'thinktank') for t in tags):
                        feed_type_cache[feed.name] = 'think_tank'
                    elif any(t in ('government', 'govt', 'gov') for t in tags):
                        feed_type_cache[feed.name] = 'government'
                    elif 'academic' in tags:
                        feed_type_cache[feed.name] = 'academic'
                    else:
                        feed_type_cache[feed.name] = 'news'

            seen_urls: set[str] = set()
            imported = 0
            for i, candidate in enumerate(unique_candidates, 1):
                if imported >= opts.max_results:
                    break
                try:
                    # Source type filter
                    if opts.source_types:
                        src = candidate.get('source', '')
                        if src in ('google_news', 'yahoo_news', 'gdelt'):
                            stype = 'news'
                        elif src in ('arxiv', 'osti', 'semantic_scholar'):
                            stype = 'academic'
                        elif src.startswith('feed:'):
                            stype = feed_type_cache.get(src[5:], 'news')
                        else:
                            stype = 'news'
                        if stype not in opts.source_types:
                            continue

                    result = _import_single_article(
                        session_id,
                        candidate["url"],
                        candidate.get("title", ""),
                        topic,
                        seen_urls,
                        opts.min_score,
                        candidate.get("published_at", ""),
                        candidate.get("source_name", ""),
                        opts.must_include,
                        opts.must_exclude,
                        opts.english_only,
                        candidate.get("description", ""),
                        candidate.get("source_domain", ""),
                    )
                    if result:
                        imported += 1
                    if i % 10 == 0:
                        db.session.commit()
                        job = ResearchJob.query.get(job_id)
                        if job:
                            job.phase_num = 8
                            job.phase = f"Scoring articles… ({i}/{len(unique_candidates)})"
                            db.session.commit()
                except Exception:
                    continue

            db.session.commit()

            job = ResearchJob.query.get(job_id)
            if job:
                job.status = "done"
                job.phase = f"Complete — {imported} articles imported"
                job.urls_found = imported
                job.completed_at = datetime.now(timezone.utc)
                db.session.commit()

        except Exception as e:
            fail_job(str(e))


@bp.route("/api/research/sessions/<int:session_id>/search", methods=["POST"])
def start_research_search(session_id):
    from flask import current_app
    flask_app = current_app._get_current_object()
    ResearchSession.query.get_or_404(session_id)

    # Block duplicate concurrent jobs
    running = ResearchJob.query.filter_by(session_id=session_id, status="running").first()
    if running:
        return jsonify({"error": "A search is already running", "job_id": running.id}), 409

    job = ResearchJob(
        session_id=session_id,
        status="pending",
        phase="Starting…",
        phase_num=0,
        total_phases=8,
        urls_found=0,
    )
    db.session.add(job)
    db.session.commit()

    session = ResearchSession.query.get(session_id)
    data = request.get_json() or {}
    date_map = {
        '1d': 1, '3d': 3, '7d': 7, '14d': 14,
        '30d': 30, '60d': 60, '90d': 90, '180d': 180,
        '365d': 365, '2y': 730, '5y': 1825,
    }
    date_range = data.get('date_range', '')
    is_custom  = date_range == 'custom'

    def _terms(raw: str) -> list[str]:
        return [t.strip() for t in raw.split(',') if t.strip()]

    opts = SearchOptions(
        topic=session.topic,
        date_days=date_map.get(date_range) if not is_custom else None,
        date_from=data.get('date_from', '') if is_custom else '',
        date_to=data.get('date_to', '')     if is_custom else '',
        min_score=max(1, min(9, int(data.get('min_score', 1)))),
        max_results=max(10, min(500, int(data.get('max_results', 50)))),
        english_only=bool(data.get('english_only', False)),
        must_include=_terms(data.get('must_include', '')),
        must_exclude=_terms(data.get('must_exclude', '')),
        source_types=data.get('source_types', []),
    )
    t = threading.Thread(
        target=run_research_search,
        args=(flask_app, job.id, session_id, session.topic, opts),
        daemon=True,
    )
    t.start()

    return jsonify({"job_id": job.id, "status": "started"})


@bp.route("/api/research/jobs/<int:job_id>/status", methods=["GET"])
def get_job_status(job_id):
    job = ResearchJob.query.get_or_404(job_id)
    return jsonify(job.to_dict())


# ── Debug endpoints (remove after troubleshooting) ────────────────────────────

@bp.route("/api/debug/research/<int:session_id>")
def debug_research_articles(session_id):
    """Return raw title + url for first 10 Google News articles in a session."""
    articles = ResearchArticle.query.filter_by(session_id=session_id).limit(20).all()
    return jsonify([
        {"id": a.id, "url": a.url[:80], "title": a.title}
        for a in articles
        if a.url and 'news.google.com' in a.url
    ][:10])


@bp.route("/api/debug/academic")
def debug_academic_search():
    """Probe arXiv and OSTI APIs directly — use ?q=your+topic to test."""
    query = request.args.get('q', 'nuclear energy')
    days = request.args.get('days', type=int)

    # Raw OSTI probe (before our parsing layer)
    osti_raw_info = {}
    try:
        r = req_lib.get(
            'https://www.osti.gov/api/v1/records',
            params={'q': query, 'rows': 3},
            headers={'Accept': 'application/json'},
            timeout=20,
        )
        osti_raw_info = {
            'status': r.status_code,
            'content_type': r.headers.get('Content-Type', ''),
            'text_sample': r.text[:600],
        }
    except Exception as exc:
        osti_raw_info = {'error': str(exc)}

    # Raw Semantic Scholar probe
    s2_raw_info = {}
    try:
        r2 = req_lib.get(
            'https://api.semanticscholar.org/graph/v1/paper/search',
            params={'query': query, 'fields': 'title,abstract,citationCount', 'limit': 3},
            timeout=20,
        )
        s2_raw_info = {
            'status': r2.status_code,
            'content_type': r2.headers.get('Content-Type', ''),
            'text_sample': r2.text[:600],
        }
    except Exception as exc:
        s2_raw_info = {'error': str(exc)}

    s2_results   = search_semantic_scholar(query, days)
    osti_results = search_osti(query, days)

    return jsonify({
        'query':            query,
        'semantic_scholar': {'parsed_count': len(s2_results),   'sample': s2_results[:2],   'raw': s2_raw_info},
        'osti':             {'parsed_count': len(osti_results),  'sample': osti_results[:2],  'raw': osti_raw_info},
    })


@bp.route("/api/debug/env")
def debug_env():
    key = os.environ.get("GROQ_API_KEY", "NOT SET")
    return jsonify({
        "key_set": key != "NOT SET",
        "key_prefix": key[:8] if key != "NOT SET" else "NOT SET",
        "key_length": len(key) if key != "NOT SET" else 0,
    })
