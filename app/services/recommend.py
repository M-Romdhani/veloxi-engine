"""Explainable recommendations sourced only from verified DB rows."""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from ..models import Difficulty
from ..pipeline.quality import deadline_boost, provider_trust, quality_score
from .opportunities import list_opportunities, to_frontend_dict

_STOP = {"the", "a", "an", "to", "for", "of", "in", "and", "or", "with", "i", "want", "learn", "get"}


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9+]+", (text or "").lower()) if t and t not in _STOP}


def recommend(
    session: Session,
    *,
    goal: str | None = None,
    free_only: bool = False,
    difficulty: str | None = None,
    certificate_only: bool = False,
    limit: int = 6,
) -> list[dict]:
    # Pull a generous candidate pool already filtered to active/non-expired rows.
    candidates = list_opportunities(
        session,
        free_only=free_only,
        difficulty=difficulty,
        certificate_only=certificate_only,
        sort="freshness",
        limit=200,
    )
    goal_tokens = _tokens(goal or "")

    scored = []
    for o in candidates:
        skills = " ".join(s.name for s in o.skills)
        haystack = _tokens(f"{o.title} {o.category} {o.description or ''} {' '.join(o.tags or [])} {skills}")
        overlap = goal_tokens & haystack
        goal_match = (len(overlap) / len(goal_tokens)) if goal_tokens else 0.0

        # Same blend the public list uses: quality leads, then freshness, then
        # how well the listing matches the stated goal, plus deadline urgency.
        total = (
            0.5 * (quality_score(o) / 100.0)
            + 0.3 * (o.freshness_score / 100.0)
            + 0.2 * goal_match
            + deadline_boost(o)
        )
        scored.append((total, overlap, o))

    scored.sort(key=lambda t: t[0], reverse=True)

    results = []
    for _, overlap, o in scored[:limit]:
        results.append({**to_frontend_dict(o), "explanation": _explain(o, goal, overlap)})
    return results


def _explain(o, goal: str | None, overlap: set[str]) -> str:
    reasons: list[str] = []
    if goal and overlap:
        topic = goal.strip().lower()
        reasons.append(f"matches your {topic} goal" if len(topic) <= 30 else "matches your goal")
    else:
        reasons.append(f"top {o.category.lower()} pick")
    if provider_trust(o.provider) >= 88:
        reasons.append("from a top-rated provider")
    if any(t in (o.tags or []) for t in ("remote", "online", "self-paced")):
        reasons.append("remote")
    if o.certificate:
        reasons.append("certificate included")
    if o.cost == 0:
        reasons.append("free")
    if o.difficulty == Difficulty.beginner.value:
        reasons.append("beginner friendly")
    return "Recommended because: " + "; ".join(reasons) + "."
