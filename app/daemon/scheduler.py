"""APScheduler wiring for the in-app background pipeline."""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ..config import settings
from ..db import SessionLocal

logger = logging.getLogger("veloxi.scheduler")


def _run_validate() -> None:
    from .validation import validate_cycle

    with SessionLocal() as session:
        try:
            summary = validate_cycle(session)
            logger.info("validate cycle: %s", summary)
        except Exception as exc:
            logger.warning("validate cycle error: %s", exc)


def _run_ingest() -> None:
    from ..ingest.runner import ingest_all

    with SessionLocal() as session:
        try:
            logs = ingest_all(session)
            logger.info("ingest cycle ran for %d sources", len(logs))
        except Exception as exc:
            logger.warning("ingest cycle error: %s", exc)


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _run_validate,
        "interval",
        minutes=settings.validate_interval_minutes,
        id="validate",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _run_ingest,
        "interval",
        minutes=settings.ingest_interval_minutes,
        id="ingest",
        max_instances=1,
        coalesce=True,
    )
    return scheduler
