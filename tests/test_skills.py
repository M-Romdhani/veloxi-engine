"""Career graph: skill inference, seeding, the skill filter, and matching."""
from sqlalchemy import func, select

from app.models import Opportunity, Skill
from app.seed import load_seed
from app.seed.skills_seed import infer_skills, slugify


def test_infer_skills_overrides_and_fallback():
    s = infer_skills("Google Data Analytics Professional Certificate", "Data & AI", ["data", "analytics"])
    assert {"SQL", "Tableau", "Data Analysis"} <= set(s)
    # Scholarships don't teach skills.
    assert infer_skills("Chevening Scholarships", "Business & PM", ["scholarship"], kind="scholarship") == []
    # Category floor when nothing else matches ("Software Development" as a
    # category name has no keyword of its own, so the floor applies cleanly).
    assert infer_skills("Some Generic Hub", "Software Development", []) == ["Programming"]
    assert slugify("Infrastructure as Code") == "infrastructure-as-code"


def test_infer_skills_token_safety():
    # "java" must not be triggered by the token "javascript".
    s = infer_skills("JavaScript Algorithms and Data Structures", "Software Development", ["javascript"])
    assert "JavaScript" in s and "Java" not in s
    # The 2-letter "ai" token must not fire on unrelated words.
    s2 = infer_skills("Technical Support Fundamentals", "IT Support", ["help desk"])
    assert "Artificial Intelligence" not in s2


def test_seed_links_skills(db):
    res = load_seed(db)
    assert res["skills_linked"] > 0

    # A flagship course carries its curated skills.
    o = db.scalars(
        select(Opportunity).where(Opportunity.title.like("Google Data Analytics%"))
    ).first()
    assert {"SQL", "Tableau"} <= {s.name for s in o.skills}

    # Every course connects to at least one skill; scholarships connect to none.
    courses = db.scalars(select(Opportunity).where(Opportunity.kind == "course")).all()
    assert courses and all(len(c.skills) >= 1 for c in courses)
    scholarships = db.scalars(select(Opportunity).where(Opportunity.kind == "scholarship")).all()
    assert scholarships and all(len(s.skills) == 0 for s in scholarships)


def test_seed_skills_idempotent(db):
    load_seed(db)
    before = db.scalar(select(func.count(Skill.id)))
    second = load_seed(db)
    assert second["skills_linked"] == 0
    assert db.scalar(select(func.count(Skill.id))) == before


def test_skills_api_and_filter(db, client):
    load_seed(db)
    skills = client.get("/api/skills").json()
    assert skills and all(s["count"] >= 1 and s["name"] and s["slug"] for s in skills)
    counts = [s["count"] for s in skills]
    assert counts == sorted(counts, reverse=True)  # busiest first

    rows = client.get("/api/opportunities", params={"skill": "SQL"}).json()
    assert rows and all("SQL" in r["skills"] for r in rows)


def test_recommend_matches_on_skill_not_in_title(db, client):
    load_seed(db)
    # "tableau" appears only as a *skill* of the Data Analytics certificate,
    # never in a title — graph-based relevance should still surface it.
    recs = client.get("/api/recommendations", params={"goal": "tableau"}).json()
    assert any("Data Analytics" in r["title"] for r in recs)
