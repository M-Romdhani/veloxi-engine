"""Aggregate stats for the public hero + admin dashboard."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import IngestionLog, Opportunity, Source, utcnow
from .opportunities import category_counts


def overview(session: Session) -> dict:
    now = utcnow()
    active = session.scalar(
        select(func.count(Opportunity.id)).where(
            Opportunity.is_active.is_(True), Opportunity.is_expired.is_(False)
        )
    )
    verified_24h = session.scalar(
        select(func.count(Opportunity.id)).where(
            Opportunity.is_active.is_(True),
            Opportunity.last_verified_at >= now - timedelta(hours=24),
        )
    )
    sources_by_status = dict(
        session.execute(select(Source.status, func.count(Source.id)).group_by(Source.status)).all()
    )
    last_ingest = session.scalar(select(func.max(IngestionLog.finished_at)))

    return {
        "activeOpportunities": int(active or 0),
        "verifiedLast24h": int(verified_24h or 0),
        "categories": category_counts(session),
        "sourcesByStatus": {k: int(v) for k, v in sources_by_status.items()},
        "lastIngestAt": last_ingest.isoformat() if last_ingest else None,
    }
