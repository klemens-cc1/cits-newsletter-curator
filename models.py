from app import db
from datetime import datetime


class Article(db.Model):
    __tablename__ = "articles"

    id          = db.Column(db.Integer, primary_key=True)
    guid        = db.Column(db.String(512), unique=True, nullable=False)
    title       = db.Column(db.Text, nullable=False)
    url         = db.Column(db.Text, nullable=False)
    feed_name   = db.Column(db.String(256), nullable=False)
    category    = db.Column(db.String(128), nullable=False)
    published_at = db.Column(db.DateTime, nullable=True)
    fetched_at  = db.Column(db.DateTime, default=datetime.utcnow)
    week_key    = db.Column(db.String(10), nullable=False)   # e.g. "2026-W09"

    # Curation fields
    status      = db.Column(db.String(20), default="unreviewed")  # unreviewed / selected / maybe / skip
    curator_note = db.Column(db.Text, nullable=True)

    # AI fields (populated lazily)
    ai_score    = db.Column(db.Integer, nullable=True)
    ai_summary  = db.Column(db.Text, nullable=True)

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
