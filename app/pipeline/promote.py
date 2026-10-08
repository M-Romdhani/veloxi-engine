"""Promote a staged RawOpportunity into the clean Opportunity table.

Order: canonicalize -> classify -> dedupe -> freshness -> upsert.
"""
from __future__ import annotations

import logging
from datetime import datetime

from dateutil import parser as dtparser
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import (
    AlertType,
    Opportunity,
    RawOpportunity,
    RawStatus,
    Source,
    utcnow,
)
from . import canonicalize, dedupe, freshness
from .classify import classify, infer_kind

logger = logging.getLogger("veloxi.promote")


def _parse_dt(value) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    try:
        return dtparser.parse(str(value))
    except (ValueError, OverflowError):
        return None


def _source_health(session: Session, source_id: int | None) -> int:
    if source_id is None:
        return 70
    src = session.get(Source, source_id)
    return src.health_score if src else 70


def promote_raw_to_opportunity(session: Session, raw: RawOpportunity) -> Opportunity | None:
    """Create or update the served Opportunity for ``raw``; mark raw promoted."""
    canon = canonicalize.canonical_url(raw.url)
    raw.canonical_url = canon
    cls = classify(raw.title, raw.description, raw.suggested_category)

    payload = raw.raw_payload or {}
    health = _source_health(session, raw.source_id)
    now = utcnow()

    cost = float(payload.get("cost", 0) or 0)
    certificate = bool(payload.get("certificate", False))
    audit = bool(payload.get("audit", False))
    duration = payload.get("duration") or "Self-paced"
    tags = payload.get("tags") or []
    expires_at = _parse_dt(payload.get("expires_at"))
    last_verified = _parse_dt(payload.get("last_verified_at")) or now
    kind = payload.get("kind") or infer_kind(raw.title, raw.description)

    existing = dedupe.find_existing_by_canonical(session, canon)
    if existing is not None:
        return _merge(session, raw, existing, health, duration, certificate, audit, tags, cls, now)

    opp = Opportunity(
        source_id=raw.source_id,
        provider=raw.provider or "Unknown",
        title=raw.title,
        category=cls.category,
        kind=kind,
        difficulty=cls.difficulty,
        cost=cost,
        audit=audit,
        certificate=certificate,
        duration=duration,
        url=raw.url,
        canonical_url=canon,
        description=raw.description or cls.summary,
        tags=tags,
        source_provider=raw.provider,
        published_at=raw.published_at,
        last_verified_at=last_verified,
        expires_at=expires_at,
        is_expired=False,
        is_active=True,
    )
    opp.freshness_score = freshness.freshness_score(
        last_verified_at=opp.last_verified_at,
        published_at=opp.published_at,
        created_at=now,
        source_health=health,
        now=now,
    )
    session.add(opp)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        existing = dedupe.find_existing_by_canonical(session, canon)
        if existing is not None:
            return _merge(session, raw, existing, health, duration, certificate, audit, tags, cls, now)
        raise

    raw.status = RawStatus.promoted.value
    raw.promoted_opportunity_id = opp.id

    from ..services import alerts  # lazy to avoid import cycle

    alerts.emit_alert(
        session,
        AlertType.new_opportunity,
        f"New opportunity discovered: {opp.title} ({opp.provider})",
        opportunity=opp,
    )
    session.flush()
    return opp


def _merge(session, raw, existing, health, duration, certificate, audit, tags, cls, now):
    existing.last_verified_at = now
    if not existing.description and cls.summary:
        existing.description = cls.summary
    if existing.duration in (None, "", "Self-paced") and duration:
        existing.duration = duration
    existing.certificate = existing.certificate or certificate
    existing.audit = existing.audit or audit
    if not existing.tags and tags:
        existing.tags = tags
    new_score = freshness.freshness_score(
        last_verified_at=existing.last_verified_at,
        published_at=existing.published_at,
        created_at=existing.created_at,
        source_health=health,
        is_active=existing.is_active,
        is_expired=existing.is_expired,
        now=now,
    )
    existing.freshness_score = max(existing.freshness_score, new_score)
    raw.status = RawStatus.promoted.value
    raw.promoted_opportunity_id = existing.id
    session.flush()
    return existing
