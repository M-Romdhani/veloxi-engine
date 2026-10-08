"""Public read API over the published opportunity index."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Opportunity
from ..services import opportunities as opp_service
from ..services import recommend as rec_service
from ..services import stats as stats_service

router = APIRouter(prefix="/api", tags=["public"])


@router.get("/opportunities")
def list_opportunities(
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
    limit: int = Query(60, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    rows = opp_service.list_opportunities(
        db,
        q=q,
        category=category,
        kind=kind,
        max_cost=max_cost,
        free_only=free_only,
        difficulty=difficulty,
        certificate_only=certificate_only,
        provider=provider,
        skill=skill,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return [opp_service.to_frontend_dict(o) for o in rows]


@router.get("/opportunities/{opp_id}")
def get_opportunity(opp_id: int, db: Session = Depends(get_db)):
    o = db.get(Opportunity, opp_id)
    if o is None or not o.is_active or o.is_expired:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return opp_service.to_frontend_dict(o)


@router.get("/categories")
def categories(db: Session = Depends(get_db)):
    return opp_service.category_counts(db)


@router.get("/providers")
def providers(db: Session = Depends(get_db)):
    return opp_service.provider_counts(db)


@router.get("/skills")
def skills(limit: int = Query(40, ge=1, le=200), db: Session = Depends(get_db)):
    return opp_service.skill_counts(db, limit=limit)


@router.get("/recommendations")
def recommendations(
    goal: str | None = None,
    free_only: bool = False,
    difficulty: str | None = None,
    certificate_only: bool = False,
    limit: int = Query(6, ge=1, le=24),
    db: Session = Depends(get_db),
):
    return rec_service.recommend(
        db,
        goal=goal,
        free_only=free_only,
        difficulty=difficulty,
        certificate_only=certificate_only,
        limit=limit,
    )


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    return stats_service.overview(db)
