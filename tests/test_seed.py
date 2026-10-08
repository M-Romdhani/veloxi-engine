from sqlalchemy import func, select

from app.models import CATEGORIES, CATEGORY_GROUPS, Opportunity, Source
from app.seed import load_seed
from app.seed.opportunities_seed import REAL_OPPORTUNITIES


def test_seed_loads_real_rows(db):
    result = load_seed(db)
    assert result["opportunities_created"] == len(REAL_OPPORTUNITIES)
    assert result["sources_created"] >= 2

    total = db.scalar(select(func.count(Opportunity.id)))
    assert total == len(REAL_OPPORTUNITIES)

    # Every category is represented.
    present = set(db.scalars(select(Opportunity.category).distinct()))
    for c in CATEGORIES:
        assert c in present, f"missing category: {c}"

    # Every URL is an absolute https link (no placeholders).
    for o in db.scalars(select(Opportunity)):
        assert o.url.startswith("https://")
        assert o.freshness_score > 0


def test_seed_has_launch_depth(db):
    """The catalog is deep (160+): the original tech categories stay substantial
    (>=12 each) and every expansion category launches with real entries (>=3)."""
    load_seed(db)
    total = db.scalar(select(func.count(Opportunity.id)))
    assert total >= 160, f"catalog too thin: {total}"

    counts = dict(
        db.execute(
            select(Opportunity.category, func.count(Opportunity.id)).group_by(Opportunity.category)
        ).all()
    )
    for c in CATEGORY_GROUPS["Technology"]:
        assert counts.get(c, 0) >= 12, f"{c} has only {counts.get(c, 0)}"
    for c in CATEGORIES:
        assert counts.get(c, 0) >= 3, f"{c} has only {counts.get(c, 0)}"


def test_seed_is_idempotent(db):
    load_seed(db)
    second = load_seed(db)
    assert second["opportunities_created"] == 0
    assert db.scalar(select(func.count(Opportunity.id))) == len(REAL_OPPORTUNITIES)
    # A real RSS source exists and is enabled.
    rss = db.scalars(select(Source).where(Source.type == "rss")).first()
    assert rss is not None and rss.is_enabled
