"""Idempotent loader for real seed sources + opportunities (no network)."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Opportunity, Skill, Source, utcnow
from ..pipeline.canonicalize import canonical_url
from ..pipeline.classify import classify
from ..pipeline.freshness import freshness_score, provider_health
from .opportunities_seed import REAL_OPPORTUNITIES
from .skills_seed import infer_skills, slugify
from .sources_seed import REAL_SOURCES


def load_sources(session: Session) -> int:
    created = 0
    for spec in REAL_SOURCES:
        existing = session.scalars(select(Source).where(Source.name == spec["name"])).first()
        if existing:
            continue
        session.add(Source(**spec))
        created += 1
    session.flush()
    return created


def load_opportunities(session: Session) -> int:
    """Upsert seed opportunities by canonical_url (re-runnable, no dupes)."""
    now = utcnow()
    created = 0
    for row in REAL_OPPORTUNITIES:
        canon = canonical_url(row["url"])
        existing = session.scalars(
            select(Opportunity).where(Opportunity.canonical_url == canon)
        ).first()

        verified_at = now - timedelta(hours=row.get("verified_hours_ago", 4))
        published_at = now - timedelta(days=row.get("published_days_ago", 30))
        expires_at = (
            now + timedelta(days=row["expires_in_days"]) if row.get("expires_in_days") else None
        )
        score = freshness_score(
            last_verified_at=verified_at,
            published_at=published_at,
            created_at=now,
            source_health=provider_health(row["provider"]),
            now=now,
        )

        if existing:
            # Re-seed fully refreshes the freshness inputs so a recalibration
            # actually lands on the live rows (no max(): scores may move down).
            existing.last_verified_at = verified_at
            existing.published_at = published_at
            existing.freshness_score = score
            existing.is_active = True
            existing.is_expired = False
            continue

        # Honor explicit category if provided, else classify from the title.
        category = row.get("category") or classify(row["title"], None).category
        session.add(
            Opportunity(
                provider=row["provider"],
                title=row["title"],
                category=category,
                kind=row.get("kind", "course"),
                difficulty=row.get("difficulty", "Beginner"),
                cost=float(row.get("cost", 0) or 0),
                audit=bool(row.get("audit", False)),
                certificate=bool(row.get("certificate", False)),
                duration=row.get("duration", "Self-paced"),
                url=row["url"],
                canonical_url=canon,
                description=row.get("description"),
                tags=row.get("tags", []),
                source_provider=row["provider"],
                published_at=published_at,
                last_verified_at=verified_at,
                expires_at=expires_at,
                is_expired=False,
                is_active=True,
                freshness_score=score,
            )
        )
        created += 1
    session.flush()
    return created


def load_skills(session: Session) -> int:
    """Link each opportunity to the skills it teaches (re-runnable, no dupes).

    Works on existing rows too, so a reseed backfills the career graph onto a
    database that was seeded before skills existed.
    """
    cache = {s.name: s for s in session.scalars(select(Skill))}
    new_links = 0
    for o in session.scalars(select(Opportunity)):
        names = infer_skills(o.title, o.category, o.tags, o.kind)
        if not names:
            continue
        existing = {s.name for s in o.skills}
        for name in names:
            skill = cache.get(name)
            if skill is None:
                skill = Skill(name=name, slug=slugify(name))
                session.add(skill)
                cache[name] = skill
            if name not in existing:
                o.skills.append(skill)
                existing.add(name)
                new_links += 1
    session.flush()
    return new_links


def load_seed(session: Session) -> dict:
    sources = load_sources(session)
    opportunities = load_opportunities(session)
    skills = load_skills(session)
    session.commit()
    return {
        "sources_created": sources,
        "opportunities_created": opportunities,
        "skills_linked": skills,
    }
