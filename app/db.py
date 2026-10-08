"""Database engine, session, and Base."""
from __future__ import annotations

import logging
import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

logger = logging.getLogger("veloxi.db")

# Where we land if DATABASE_URL is missing or unparseable, so a bad env var
# degrades to local storage instead of crash-looping the entire deployment.
_SQLITE_FALLBACK = "sqlite:////data/veloxi.db"


class Base(DeclarativeBase):
    pass


def _normalize_db_url(url: str) -> str:
    """Accept Heroku/Render-style Postgres URLs and target the psycopg3 driver.

    Also tolerate values that arrive wrapped in whitespace or quotes -- a common
    copy-paste / shell-escaping mistake when setting the var in a dashboard.
    """
    url = (url or "").strip().strip("'\"").strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def _resolve_database_url(raw: str) -> str:
    """Normalize DATABASE_URL and guarantee it is a parseable SQLAlchemy URL.

    If it isn't -- empty, an unexpanded ``${{Postgres.DATABASE_URL}}`` reference,
    or otherwise malformed -- log loudly and fall back to a local SQLite file so
    the web server still boots and ``/health`` stays available. The deploy goes
    green and the misconfiguration shows up in the logs, instead of an
    import-time crash loop that hides the cause.
    """
    url = _normalize_db_url(raw)
    try:
        make_url(url)
    except ArgumentError:
        logger.error(
            "DATABASE_URL is not a valid SQLAlchemy URL (%r); falling back to %s so the "
            "app can still boot. Set DATABASE_URL to a valid Postgres connection string "
            "to persist data.",
            raw[:80],
            _SQLITE_FALLBACK,
        )
        return _SQLITE_FALLBACK
    return url


DATABASE_URL = _resolve_database_url(settings.database_url)


def _engine_kwargs(url: str) -> dict:
    if url.startswith("sqlite"):
        # Allow use across threads (FastAPI + APScheduler) for the SQLite dev DB.
        return {"connect_args": {"check_same_thread": False}}
    return {}


def _ensure_sqlite_dir(url: str) -> None:
    """Create the parent directory for a file-based SQLite DB if it's missing.

    Keeps the default ``sqlite:////data/veloxi.db`` working on hosts that don't
    pre-create the directory (e.g. Railway without a mounted volume). In-memory
    DBs (used in tests) have no path and are skipped.
    """
    if not url.startswith("sqlite"):
        return
    database = make_url(url).database
    if not database or database == ":memory:":
        return
    os.makedirs(os.path.dirname(os.path.abspath(database)), exist_ok=True)


_ensure_sqlite_dir(DATABASE_URL)
engine = create_engine(DATABASE_URL, future=True, **_engine_kwargs(DATABASE_URL))
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Additive micro-migrations: create_all only creates missing *tables*, so new
# columns on existing tables are declared here and ALTERed in at boot. Only
# nullable/defaulted columns belong in this map -- never type changes or drops.
_ENSURE_COLUMNS: dict[str, dict[str, str]] = {
    "user_profiles": {
        "country": "VARCHAR(100)",
        "birth_year": "INTEGER",
    },
}


def _ensure_columns() -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in _ENSURE_COLUMNS.items():
            if table not in tables:
                continue  # create_all will create it with the full schema
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    logger.info("Schema: added column %s.%s", table, name)


def init_db() -> None:
    """Create all tables and apply additive column migrations. Idempotent."""
    from . import models  # noqa: F401  (register mappers)

    Base.metadata.create_all(bind=engine)
    _ensure_columns()
