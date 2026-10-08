"""Career Agent prototype — deterministic engine (no LLM/network in tests)."""
from sqlalchemy import func, select

from app.models import CareerReport
from app.seed import load_seed
from app.services import career


CV = """
Jane Doe — Junior Analyst
Skills: Python, SQL, Excel. Built dashboards and cleaned data for reporting.
"""


def test_extract_have_skills_matches_vocabulary(db):
    load_seed(db)
    have = career.extract_have_skills(db, "Experienced in Python, JavaScript, and Figma.")
    assert {"Python", "JavaScript", "Figma"} <= set(have)
    # Single-letter skills must not fire on arbitrary words.
    assert "R" not in career.extract_have_skills(db, "Strong communicator and reporter.")


def test_analyze_produces_gap_and_roadmap(db):
    load_seed(db)
    res = career.analyze(db, cv_text=CV, goal="Data Analyst")

    assert {"Python", "SQL", "Excel"} <= set(res["haveSkills"])
    assert res["targetSkills"] and res["gapSkills"]
    assert res["llmUsed"] is False  # no API key in tests

    have = set(res["haveSkills"])
    assert all(s not in have for s in res["gapSkills"])  # gap excludes what you have

    # Every match closes at least one gap skill, and only gap skills are credited.
    assert res["matches"]
    gap = set(res["gapSkills"])
    for m in res["matches"]:
        assert m["coversSkills"] and set(m["coversSkills"]) <= gap

    # Roadmap is ordered beginner -> advanced.
    order = {"Beginner": 0, "Intermediate": 1, "Advanced": 2}
    levels = [order.get(s["difficulty"], 1) for s in res["roadmap"]]
    assert levels == sorted(levels)


def test_analyze_persists_derived_report_only(db):
    load_seed(db)
    res = career.analyze(db, cv_text=CV, goal="Data Analyst")
    report = db.get(CareerReport, res["reportId"])
    assert report is not None
    assert report.gap_skills == res["gapSkills"]
    assert report.matched_ids == [m["id"] for m in res["matches"]]
    # Privacy: the raw CV is never stored on the model.
    assert not hasattr(report, "cv_text")
    assert "cv_text" not in {c.name for c in CareerReport.__table__.columns}


def test_career_endpoint_requires_admin(client):
    assert client.post("/admin/career/analyze", json={"cv_text": CV}).status_code == 401


def test_career_endpoint_returns_analysis(db, client):
    load_seed(db)
    r = client.post(
        "/admin/career/analyze",
        headers={"X-Admin-Token": "test-token"},
        json={"cv_text": CV, "goal": "Data Analyst"},
    )
    assert r.status_code == 200
    body = r.json()
    for key in ("haveSkills", "targetSkills", "gapSkills", "matches", "roadmap", "reportId"):
        assert key in body

    # Empty CV is rejected.
    bad = client.post(
        "/admin/career/analyze",
        headers={"X-Admin-Token": "test-token"},
        json={"cv_text": "   "},
    )
    assert bad.status_code == 422

    reports = client.get("/admin/career/reports", headers={"X-Admin-Token": "test-token"}).json()
    assert reports and reports[0]["goal"] == "Data Analyst"
    assert db.scalar(select(func.count(CareerReport.id))) >= 1
