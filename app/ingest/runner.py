"""Run adapters: pull -> stage RawOpportunity -> promote -> log."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    IngestionLog,
    RawOpportunity,
    RawStatus,
    Source,
    SourceStatus,
    SourceType,
    utcnow,
)
from ..pipeline.opportunity_filter import looks_like_opportunity
from ..pipeline.promote import promote_raw_to_opportunity
from . import apify, api_json, manual, rss, scraper  # noqa: F401  (register adapters)
from .base import AdapterRegistry, RawItem

logger = logging.getLogger("veloxi.ingest")


def _framing(source: Source) -> dict:
    """Per-source defaults (cost/cert/etc.) used to frame items that lack them.

    RSS items carry only title/link/date, so a source can declare how its items
    should appear via config.default_cost / default_certificate / default_audit /
    default_duration / default_tags.
    """
    cfg = source.config or {}
    out = {}
    for field, key in (
        ("cost", "default_cost"),
        ("certificate", "default_certificate"),
        ("audit", "default_audit"),
        ("duration", "default_duration"),
        ("tags", "default_tags"),
        ("kind", "default_kind"),
    ):
        if key in cfg:
            out[field] = cfg[key]
    return out


def _stage_item(session: Session, source: Source, item: RawItem) -> bool:
    """Insert a RawOpportunity if not already staged. Returns True if new."""
    if item.external_id:
        dup = session.scalars(
            select(RawOpportunity).where(
                RawOpportunity.source_id == source.id,
                RawOpportunity.external_id == item.external_id,
            )
        ).first()
        if dup is not None:
            return False
    payload = {**_framing(source), **(item.raw_payload or {})}
    cfg = source.config or {}
    session.add(
        RawOpportunity(
            source_id=source.id,
            external_id=item.external_id,
            title=item.title,
            url=item.url,
            description=item.description,
            provider=item.provider or source.default_provider,
            suggested_category=item.suggested_category or cfg.get("default_category"),
            published_at=item.published_at,
            raw_payload=payload,
            status=RawStatus.pending.value,
        )
    )
    session.flush()
    return True


def ingest_source(session: Session, source: Source) -> IngestionLog:
    """Ingest one source. Network/adapter failures are logged, never raised."""
    log = IngestionLog(source_id=source.id, started_at=utcnow())
    session.add(log)
    session.flush()
    try:
        adapter = AdapterRegistry.for_source(source)
        items = list(adapter.fetch())
        log.items_seen = len(items)
        for item in items:
            # Keep blog/news articles out of the queue (manual sources bypass).
            if source.type != SourceType.manual.value and not looks_like_opportunity(item, source):
                continue
            if _stage_item(session, source, item):
                log.items_new += 1
        session.flush()

        # Auto-promote freshly-staged items from non-manual sources, unless the
        # source opts out (config.auto_promote=false) to route items through the
        # admin approval queue. Manual submissions are always admin-governed.
        auto = (source.config or {}).get("auto_promote", settings.auto_promote)
        if auto and source.type != SourceType.manual.value:
            pending = session.scalars(
                select(RawOpportunity).where(
                    RawOpportunity.source_id == source.id,
                    RawOpportunity.status == RawStatus.pending.value,
                )
            ).all()
            for raw in pending:
                promote_raw_to_opportunity(session, raw)
                if raw.status == RawStatus.promoted.value:
                    log.items_promoted += 1
                session.commit()  # isolate any canonical-race rollback per item

        source.last_ingested_at = utcnow()
        if source.type != SourceType.manual.value:
            source.status = SourceStatus.verified.value
            source.consecutive_failures = 0
            source.health_score = min(100, source.health_score + 5)
        log.ok = True
    except NotImplementedError as exc:
        log.ok = False
        log.message = f"adapter not implemented: {exc}"
    except Exception as exc:
        logger.info("ingest failed for source %s: %s", source.id, exc)
        log.ok = False
        log.message = str(exc)[:900]
        source.consecutive_failures += 1
        source.health_score = max(0, source.health_score - 25)
        source.status = SourceStatus.unreachable.value

    log.finished_at = utcnow()
    session.commit()
    return log


def ingest_all(session: Session) -> list[IngestionLog]:
    sources = session.scalars(select(Source).where(Source.is_enabled.is_(True))).all()
    return [ingest_source(session, s) for s in sources]
