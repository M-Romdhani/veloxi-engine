"""Career Agent.

Pipeline: CV text -> skills you have -> skills your goal needs (from the career
graph) -> the gap -> verified courses that close it (greedy set-cover) -> an
ordered roadmap. The engine is fully deterministic and runs on the skills graph
seeded in Phase 1c — no API key required. When an LLM is configured it augments
the extracted skills and adds a one-line summary.

Privacy: the CV is processed in memory and never stored. Only derived results
(skills, gap, recommended opportunity ids) are persisted in ``CareerReport``.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CareerReport, Difficulty, Skill
from ..pipeline.llm import extract_profile_with_llm
from ..pipeline.quality import rank_score
from .opportunities import list_opportunities, to_frontend_dict

_DIFF_ORDER = {
    Difficulty.beginner.value: 0,
    Difficulty.intermediate.value: 1,
    Difficulty.advanced.value: 2,
}


def _known_skills(session: Session) -> dict[str, str]:
    """Lowercased name -> canonical Skill name for the whole vocabulary."""
    return {s.name.lower(): s.name for s in session.scalars(select(Skill))}


def extract_have_skills(session: Session, cv_text: str, extra: list[str] | None = None) -> list[str]:
    """Skills the candidate already has — matched against the graph vocabulary.

    Multi-word skills match as a substring; single-word skills match as a whole
    token (so "r" / "ai" don't fire on arbitrary letters inside other words).
    ``extra`` (e.g. LLM-extracted names) is folded in when it maps to a known skill.
    """
    known = _known_skills(session)
    text = (cv_text or "").lower()
    tokens = {t for t in re.split(r"[^a-z0-9+#]+", text) if t}

    have: set[str] = set()
    for low, name in known.items():
        if any(c in low for c in (" ", "/", "-")):
            if low in text:
                have.add(name)
        elif low in tokens:
            have.add(name)

    for raw in extra or []:
        low = str(raw).strip().lower()
        if low in known:
            have.add(known[low])

    return sorted(have)


def target_skills(
    session: Session,
    *,
    goal: str | None = None,
    category: str | None = None,
    pool: int = 40,
    top_k: int = 14,
) -> list[str]:
    """Skills the goal demands — the most common skills taught by the top
    quality-ranked courses for that goal/category."""
    courses = list_opportunities(
        session, q=goal, category=category, kind="course", limit=pool
    )
    counts: dict[str, int] = {}
    for o in courses:
        for s in o.skills:
            counts[s.name] = counts.get(s.name, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    return [name for name, _ in ranked[:top_k]]


def _match_opportunities(
    session: Session, gap: list[str], *, goal: str | None, max_matches: int
) -> list[dict]:
    """Greedy set-cover: pick the fewest high-quality courses that close the gap.

    Each round picks the course covering the most still-uncovered gap skills,
    breaking ties by blended quality rank.
    """
    if not gap:
        return []
    remaining = set(gap)
    pool = list_opportunities(session, q=goal, kind="course", limit=200)
    used: set[int] = set()
    chosen: list[dict] = []

    while remaining and len(chosen) < max_matches:
        scored = []
        for o in pool:
            if o.id in used:
                continue
            covered = {s.name for s in o.skills} & remaining
            if covered:
                scored.append((len(covered), rank_score(o, goal), o, covered))
        if not scored:
            break
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        _, _, opp, covered = scored[0]
        used.add(opp.id)
        remaining -= covered
        row = to_frontend_dict(opp)
        row["coversSkills"] = sorted(covered)
        chosen.append(row)
    return chosen


def _roadmap(matches: list[dict]) -> list[dict]:
    """Order the chosen courses beginner -> advanced into numbered steps."""
    ordered = sorted(matches, key=lambda m: _DIFF_ORDER.get(m.get("difficulty"), 1))
    return [
        {
            "step": i,
            "title": m["title"],
            "provider": m["provider"],
            "url": m["url"],
            "difficulty": m["difficulty"],
            "skills": m.get("coversSkills", []),
        }
        for i, m in enumerate(ordered, 1)
    ]


def analyze(
    session: Session,
    *,
    cv_text: str,
    goal: str | None = None,
    category: str | None = None,
    max_matches: int = 6,
) -> dict:
    """Run the full Career Agent pipeline and persist a derived report."""
    profile = extract_profile_with_llm(cv_text)  # None unless an LLM is configured
    llm_skills = (profile or {}).get("skills") or []
    if not goal and profile and profile.get("targetRole"):
        goal = profile["targetRole"]

    have = extract_have_skills(session, cv_text, extra=llm_skills)
    target = target_skills(session, goal=goal, category=category)
    have_set = set(have)
    gap = [s for s in target if s not in have_set]
    matches = _match_opportunities(session, gap, goal=goal, max_matches=max_matches)

    report = CareerReport(
        goal=goal or "",
        have_skills=have,
        target_skills=target,
        gap_skills=gap,
        matched_ids=[m["id"] for m in matches],
        llm_used=bool(profile),
    )
    session.add(report)
    session.commit()

    return {
        "goal": goal or "",
        "summary": (profile or {}).get("summary") or "",
        "llmUsed": bool(profile),
        "haveSkills": have,
        "targetSkills": target,
        "gapSkills": gap,
        "matches": matches,
        "roadmap": _roadmap(matches),
        "reportId": report.id,
    }
