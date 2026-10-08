"""Dedupe opportunities by canonical URL."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Opportunity


def find_existing_by_canonical(session: Session, canonical: str) -> Opportunity | None:
    if not canonical:
        return None
    return session.scalars(
        select(Opportunity).where(Opportunity.canonical_url == canonical)
    ).first()
