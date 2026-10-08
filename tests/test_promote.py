from sqlalchemy import func, select

from app.models import Alert, AlertType, Opportunity, RawOpportunity, RawStatus, Source, SourceType
from app.pipeline.promote import promote_raw_to_opportunity


def _make_source(db):
    src = Source(name="Test", type=SourceType.rss.value, url="https://feed.example.com/rss")
    db.add(src)
    db.flush()
    return src


def test_promote_creates_clean_opportunity(db):
    src = _make_source(db)
    raw = RawOpportunity(
        source_id=src.id,
        external_id="x1",
        title="AWS Cloud Practitioner Essentials",
        url="https://aws.amazon.com/training/?utm_source=feed",
        provider="AWS",
        raw_payload={"cost": 0, "certificate": True, "duration": "6 hours"},
        status=RawStatus.pending.value,
    )
    db.add(raw)
    db.flush()

    opp = promote_raw_to_opportunity(db, raw)
    db.commit()

    assert opp is not None
    assert opp.canonical_url == "https://aws.amazon.com/training"
    assert opp.category == "Cloud Computing"
    assert opp.certificate is True
    assert opp.freshness_score > 0
    assert raw.status == RawStatus.promoted.value
    assert raw.promoted_opportunity_id == opp.id

    alerts = db.scalars(select(Alert).where(Alert.type == AlertType.new_opportunity.value)).all()
    assert len(alerts) == 1


def test_dedupe_collapses_equivalent_urls(db):
    src = _make_source(db)
    raw1 = RawOpportunity(
        source_id=src.id, external_id="a",
        title="CS50", url="https://www.edx.org/learn/cs50/", status=RawStatus.pending.value,
    )
    raw2 = RawOpportunity(
        source_id=src.id, external_id="b",
        title="CS50", url="http://edx.org/learn/cs50?utm_source=x", status=RawStatus.pending.value,
    )
    db.add_all([raw1, raw2])
    db.flush()

    promote_raw_to_opportunity(db, raw1)
    db.commit()
    promote_raw_to_opportunity(db, raw2)
    db.commit()

    count = db.scalar(select(func.count(Opportunity.id)))
    assert count == 1
    assert raw1.promoted_opportunity_id == raw2.promoted_opportunity_id
