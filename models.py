from app import db
from datetime import datetime, timezone


class Article(db.Model):
    __tablename__ = "articles"

    id           = db.Column(db.Integer, primary_key=True)
    guid         = db.Column(db.String(512), unique=True, nullable=False)
    title        = db.Column(db.Text, nullable=False)
    url          = db.Column(db.Text, nullable=False)
    feed_name    = db.Column(db.String(256), nullable=False)
    category     = db.Column(db.String(128), nullable=False)
    published_at = db.Column(db.DateTime, nullable=True)
    fetched_at   = db.Column(db.DateTime, default=datetime.utcnow)
    week_key     = db.Column(db.String(10), nullable=False)

    # Curation fields
    status       = db.Column(db.String(20), default="unreviewed")
    curator_note = db.Column(db.Text, nullable=True)

    # AI fields (populated lazily)
    ai_score     = db.Column(db.Integer, nullable=True)
    ai_summary   = db.Column(db.Text, nullable=True)

    def to_dict(self):
        return {
            "id":           self.id,
            "guid":         self.guid,
            "title":        self.title,
            "url":          self.url,
            "feed_name":    self.feed_name,
            "category":     self.category,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "fetched_at":   self.fetched_at.isoformat() if self.fetched_at else None,
            "week_key":     self.week_key,
            "status":       self.status,
            "curator_note": self.curator_note,
            "ai_score":     self.ai_score,
            "ai_summary":   self.ai_summary,
        }


class RefreshLog(db.Model):
    __tablename__ = "refresh_log"

    id               = db.Column(db.Integer, primary_key=True)
    week_key         = db.Column(db.String(10), nullable=False)
    articles_added   = db.Column(db.Integer, default=0)
    articles_skipped = db.Column(db.Integer, default=0)
    triggered_by     = db.Column(db.String(20), default="digest")  # digest | curate
    pushed_at        = db.Column(db.DateTime, default=datetime.utcnow)
    note             = db.Column(db.Text, nullable=True)

    def to_dict(self):
        return {
            "id":               self.id,
            "week_key":         self.week_key,
            "articles_added":   self.articles_added,
            "articles_skipped": self.articles_skipped,
            "triggered_by":     self.triggered_by,
            "pushed_at":        self.pushed_at.isoformat() if self.pushed_at else None,
            "note":             self.note,
        }


class ResearchSession(db.Model):
    __tablename__ = "research_sessions"

    id         = db.Column(db.Integer, primary_key=True)
    topic      = db.Column(db.Text, nullable=False)
    owner      = db.Column(db.String(128), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    articles = db.relationship("ResearchArticle", backref="session",
                               lazy=True, cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id":         self.id,
            "topic":      self.topic,
            "owner":      self.owner,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "article_count": len(self.articles),
        }


class ResearchArticle(db.Model):
    __tablename__ = "research_articles"

    id              = db.Column(db.Integer, primary_key=True)
    session_id      = db.Column(db.Integer, db.ForeignKey("research_sessions.id"), nullable=False)
    url             = db.Column(db.Text, nullable=False)
    title           = db.Column(db.Text, nullable=True)
    description     = db.Column(db.Text, nullable=True)
    relevance_score = db.Column(db.Integer, nullable=True)
    status          = db.Column(db.String(20), default="unreviewed")
    curator_note    = db.Column(db.Text, nullable=True)
    created_at      = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id":              self.id,
            "session_id":      self.session_id,
            "url":             self.url,
            "title":           self.title,
            "description":     self.description,
            "relevance_score": self.relevance_score,
            "status":          self.status,
            "curator_note":    self.curator_note,
            "created_at":      self.created_at.isoformat() if self.created_at else None,
        }
