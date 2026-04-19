import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


def create_app():
    app = Flask(__name__)

    database_url = os.environ.get("DATABASE_URL", "sqlite:///curator.db")
    # Render uses postgres:// but SQLAlchemy needs postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")

    db.init_app(app)

    from routes import bp
    app.register_blueprint(bp)

    with app.app_context():
        db.create_all()
        _run_migrations(db)

    return app


def _run_migrations(db):
    """Apply additive schema changes that db.create_all() won't handle."""
    migrations = [
        "ALTER TABLE research_articles ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ",
        "ALTER TABLE research_articles ADD COLUMN IF NOT EXISTS source_name VARCHAR(256)",
        "ALTER TABLE research_articles ADD COLUMN IF NOT EXISTS source_domain VARCHAR(256)",
    ]
    try:
        with db.engine.connect() as conn:
            for sql in migrations:
                conn.execute(db.text(sql))
            conn.commit()
    except Exception:
        pass  # SQLite (local dev) doesn't support IF NOT EXISTS — safe to ignore
