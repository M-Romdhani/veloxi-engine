"""DATABASE_URL normalization + resilient fallback.

A malformed DATABASE_URL must never crash the app at import time (which would
take down /health and the whole deploy); it should degrade to local SQLite.
"""
from app.db import _normalize_db_url, _resolve_database_url


def test_postgres_scheme_normalized_to_psycopg():
    assert _resolve_database_url("postgres://u:p@h:5432/db") == "postgresql+psycopg://u:p@h:5432/db"
    assert _resolve_database_url("postgresql://u:p@h:5432/db") == "postgresql+psycopg://u:p@h:5432/db"


def test_strips_surrounding_quotes_and_whitespace():
    assert _normalize_db_url('  "postgresql://u:p@h/db" ') == "postgresql+psycopg://u:p@h/db"


def test_unparseable_url_falls_back_to_sqlite():
    # Unexpanded Railway reference, empty, and garbage must all degrade, not crash.
    assert _resolve_database_url("${{Postgres.DATABASE_URL}}").startswith("sqlite")
    assert _resolve_database_url("").startswith("sqlite")
    assert _resolve_database_url("   ").startswith("sqlite")


def test_valid_urls_pass_through_unchanged():
    assert _resolve_database_url("sqlite:////data/veloxi.db") == "sqlite:////data/veloxi.db"
    assert _resolve_database_url("sqlite://") == "sqlite://"
