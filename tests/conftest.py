"""Shared pytest fixtures — in-memory SQLite, no network."""
from __future__ import annotations

import os

# Configure the app for tests BEFORE importing any app module.
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("INGEST_ENABLED", "false")
os.environ.setdefault("LLM_PROVIDER", "")
os.environ.setdefault("ADMIN_TOKEN", "test-token")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import models  # noqa: E402,F401  (register mappers)
from app.db import Base, get_db  # noqa: E402


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def Session(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture
def db(Session):
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(Session):
    from fastapi.testclient import TestClient

    from app.main import app

    def _override():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
