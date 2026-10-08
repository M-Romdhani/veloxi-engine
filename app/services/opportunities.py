"""Public opportunity queries + frontend serialization."""
from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import CATEGORIES, CATEGORY_GROUPS, Opportunity, Skill, opportunity_skills
from ..pipeline.freshness import freshness_label
from ..pipeline.quality import days_remaining, quality_score, rank_score


def _num(value: float):
    """Render whole floats as ints so the frontend sees 0/39/49 not 0.0."""
    return int(value) if float(value).is_integer() else float(value)


def to_frontend_dict(o: Opportunity) -> dict:
    return {
        "id": o.id,
        "provider": o.provider,
        "title": o.title,
        "category": o.category,
        "kind": o.kind,
        "difficulty": o.difficulty,
        "cost": _num(o.cost),
        "audit": o.audit,
        "certificate": o.certificate,
        "duration": o.duration,
        "freshnessLabel": freshness_label(o.last_verified_at),
        "freshnessScore": o.freshness_score,
        "qualityScore": quality_score(o),
        "url": o.url,
        "sourceUrl": o.url,
        "lastVerifiedAt": o.last_verified_at.isoformat() if o.last_verified_at else None,
        "expiresAt": o.expires_at.isoformat() if o.expires_at else None,
        "daysRemaining": days_remaining(o.expires_at),
        "skills": [s.name for s in o.skills],
    }


def _active(stmt):
    return stmt.where(Opportunity.is_active.is_(True), Opportunity.is_expired.is_(False))


def _apply_filters(stmt, *, q, category, kind, max_cost, free_only, difficulty, certificate_only, provider=None, skill=None):
    if q:
        term = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Opportunity.title).like(term),
                func.lower(Opportunity.provider).like(term),
                func.lower(Opportunity.category).like(term),
                func.lower(func.coalesce(Opportunity.description, "")).like(term),
            )
        )
    if category and category != "All":
        stmt = stmt.where(Opportunity.category == category)
    if provider and provider != "All":
        stmt = stmt.where(Opportunity.provider == provider)
    if kind and kind != "All":
        stmt = stmt.where(Opportunity.kind == kind)
    if difficulty and difficulty != "All":
        stmt = stmt.where(Opportunity.difficulty == difficulty)
    if certificate_only:
        stmt = stmt.where(Opportunity.certificate.is_(True))
    if skill and skill != "All":
        stmt = stmt.where(Opportunity.skills.any(or_(Skill.name == skill, Skill.slug == skill)))
    if free_only:
        stmt = stmt.where(Opportunity.cost == 0)
    elif max_cost is not None:
        stmt = stmt.where(Opportunity.cost <= max_cost)
    return stmt


def list_opportunities(
    session: Session,
    *,
    q: str | None = None,
    category: str | None = None,
    kind: str | None = None,
    max_cost: float | None = None,
    free_only: bool = False,
    difficulty: str | None = None,
    certificate_only: bool = False,
    provider: str | None = None,
    skill: str | None = None,
    sort: str = "quality",
    limit: int = 60,
    offset: int = 0,
) -> list[Opportunity]:
    stmt = _apply_filters(
        _active(select(Opportunity)),
        q=q,
        category=category,
        kind=kind,
        max_cost=max_cost,
        free_only=free_only,
        difficulty=difficulty,
        certificate_only=certificate_only,
        provider=provider,
        skill=skill,
    )
    if sort == "cost":
        stmt = stmt.order_by(Opportunity.cost.asc(), Opportunity.freshness_score.desc())
    elif sort == "recent":
        stmt = stmt.order_by(
            func.coalesce(Opportunity.published_at, Opportunity.created_at).desc()
        )
    elif sort == "freshness":
        stmt = stmt.order_by(Opportunity.freshness_score.desc(), Opportunity.id.desc())
    else:  # "quality" (default): blended rank, computed in Python over the pool
        pool = list(session.scalars(stmt.order_by(Opportunity.id.desc()).limit(200)))
        pool.sort(key=lambda o: rank_score(o, q), reverse=True)
        start = max(0, offset)
        return pool[start : start + max(1, min(limit, 200))]
    stmt = stmt.limit(max(1, min(limit, 200))).offset(max(0, offset))
    return list(session.scalars(stmt))


def category_counts(session: Session) -> list[dict]:
    """Active counts per category, tagged with its section (for grouped filters)."""
    rows = dict(
        session.execute(
            _active(select(Opportunity.category, func.count(Opportunity.id))).group_by(
                Opportunity.category
            )
        ).all()
    )
    group_of = {c: g for g, cats in CATEGORY_GROUPS.items() for c in cats}
    return [
        {"name": c, "count": int(rows.get(c, 0)), "group": group_of[c]}
        for c in CATEGORIES
    ]


def provider_counts(session: Session) -> list[dict]:
    """Active counts per provider, busiest first (for the live providers strip)."""
    rows = session.execute(
        _active(select(Opportunity.provider, func.count(Opportunity.id)))
        .group_by(Opportunity.provider)
        .order_by(func.count(Opportunity.id).desc(), Opportunity.provider.asc())
    ).all()
    return [{"name": p, "count": int(n)} for p, n in rows if p]


def skill_counts(session: Session, limit: int = 40) -> list[dict]:
    """Active opportunity counts per skill, busiest first (career-graph browse)."""
    rows = session.execute(
        select(Skill.name, Skill.slug, func.count(opportunity_skills.c.opportunity_id))
        .join(opportunity_skills, Skill.id == opportunity_skills.c.skill_id)
        .join(Opportunity, Opportunity.id == opportunity_skills.c.opportunity_id)
        .where(Opportunity.is_active.is_(True), Opportunity.is_expired.is_(False))
        .group_by(Skill.name, Skill.slug)
        .order_by(func.count(opportunity_skills.c.opportunity_id).desc(), Skill.name.asc())
        .limit(max(1, min(limit, 200)))
    ).all()
    return [{"name": n, "slug": s, "count": int(c)} for n, s, c in rows]
