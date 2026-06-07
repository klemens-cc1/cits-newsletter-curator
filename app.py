import logging
import os
import time
from datetime import datetime

from flask import Flask
from flask_sqlalchemy import SQLAlchemy

log = logging.getLogger(__name__)

db = SQLAlchemy()


def create_app():
    app = Flask(__name__)

    database_url = os.environ.get("DATABASE_URL", "sqlite:///curator.db")
    # Render uses postgres:// but SQLAlchemy needs postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,   # test connections before use; recovers after Supabase resume
        "pool_recycle": 1800,    # recycle connections every 30 min to avoid server-side timeout
    }
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")

    db.init_app(app)

    from routes import bp
    app.register_blueprint(bp)

    import osint_models  # noqa: F401 — registers ORM models so db.create_all() sees them
    from osint_routes import osint_bp
    app.register_blueprint(osint_bp)

    with app.app_context():
        _init_db(retries=6, base_delay=3)

    return app


def _init_db(retries: int = 6, base_delay: int = 3) -> None:
    """Create tables and run migrations, retrying on transient DNS/connection errors.

    Render's internal database hostname can be unresolvable for a few seconds
    during a cold-start before the private network is fully ready.
    """
    for attempt in range(1, retries + 1):
        try:
            db.create_all()
            _run_migrations(db)
            return
        except Exception as exc:
            if attempt >= retries:
                log.error("DB init failed after %d attempts: %s", retries, exc)
                raise
            delay = base_delay * attempt   # 3 s, 6 s, 9 s, 12 s, 15 s
            log.warning(
                "DB not ready (attempt %d/%d): %s — retrying in %ds",
                attempt, retries, exc, delay,
            )
            time.sleep(delay)


def _run_migrations(db):
    """Apply additive schema changes that db.create_all() won't handle."""
    migrations = [
        "ALTER TABLE research_articles ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ",
        "ALTER TABLE research_articles ADD COLUMN IF NOT EXISTS source_name VARCHAR(256)",
        "ALTER TABLE research_articles ADD COLUMN IF NOT EXISTS source_domain VARCHAR(256)",
        "CREATE TABLE IF NOT EXISTS feedback (id SERIAL PRIMARY KEY, message TEXT NOT NULL, submitted_at TIMESTAMPTZ DEFAULT NOW())",
        "ALTER TABLE research_sessions ADD COLUMN IF NOT EXISTS search_params TEXT",
    ]
    try:
        with db.engine.connect() as conn:
            for sql in migrations:
                conn.execute(db.text(sql))
            conn.commit()
    except Exception:
        pass  # SQLite (local dev) doesn't support IF NOT EXISTS — safe to ignore
