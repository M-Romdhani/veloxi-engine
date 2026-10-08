"""FastAPI application factory."""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import __version__
from .config import settings
from .db import init_db
from .routers import admin, public

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("veloxi")


def _init_db_with_retry(attempts: int = 5, delay_seconds: float = 2.0) -> None:
    """Create tables, tolerating a database that isn't reachable yet.

    On platforms like Railway, private networking (and thus the Postgres host
    ``*.railway.internal``) can take a few seconds to resolve after the
    container starts. Retry briefly, but never let a DB hiccup stop the web
    server from booting -- ``/health`` must stay available so the platform's
    healthcheck passes. If the DB is still unreachable, log loudly and serve
    anyway; requests that need it will surface the error per-request.
    """
    for attempt in range(1, attempts + 1):
        try:
            init_db()
            logger.info("Database initialized.")
            return
        except Exception as exc:  # noqa: BLE001 - boot must be resilient
            if attempt == attempts:
                logger.error(
                    "Database init failed after %d attempts (%s). Serving anyway; "
                    "requests needing the DB will error until it is reachable.",
                    attempts,
                    exc,
                )
                return
            logger.warning(
                "Database not ready (attempt %d/%d): %s; retrying in %.0fs",
                attempt,
                attempts,
                exc,
                delay_seconds,
            )
            time.sleep(delay_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_db_with_retry()
    scheduler = None
    if settings.ingest_enabled:
        try:
            from .daemon.scheduler import build_scheduler

            scheduler = build_scheduler()
            scheduler.start()
            logger.info("Background pipeline started (INGEST_ENABLED=true).")
        except Exception:
            # A scheduler problem must never take down the web server.
            logger.exception("Failed to start background pipeline; serving without it.")
            scheduler = None
    else:
        logger.info("Background pipeline disabled (set INGEST_ENABLED=true to enable).")
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    app = FastAPI(title="Veloxi Engine", version=__version__, lifespan=lifespan)
    app.include_router(public.router)
    app.include_router(admin.router)

    @app.get("/", include_in_schema=False)
    def root():
        return {"name": "veloxi-engine", "docs": "/docs", "health": "/health"}

    @app.get("/health", include_in_schema=False)
    def health():
        return {"status": "ok", "version": __version__}

    return app


app = create_app()
