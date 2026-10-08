from sqlalchemy import func, select

from app.ingest import runner
from app.ingest.base import RawItem
from app.ingest.rss import RSSAdapter
from app.models import Opportunity, RawOpportunity, RawStatus, Source, SourceType

ITEMS = [
    RawItem(title="Intro to Cloud Computing on AWS", url="https://aws.example.com/intro", external_id="a1"),
    RawItem(title="Advanced Kubernetes Deep Dive", url="https://k8s.example.com/adv", external_id="a2"),
]


def _source(db, config):
    s = Source(name="Feed", type=SourceType.rss.value, url="https://feed.example.com/rss", config=config)
    db.add(s)
    db.flush()
    return s


def test_feed_routes_to_queue_with_framing(db, monkeypatch):
    monkeypatch.setattr(RSSAdapter, "fetch", lambda self: list(ITEMS))
    src = _source(db, {"default_cost": 0, "default_certificate": True, "default_duration": "Self-paced", "auto_promote": False, "trust_all_items": True})

    log = runner.ingest_source(db, src)
    assert (log.items_seen, log.items_new, log.items_promoted) == (2, 2, 0)

    pending = db.scalars(
        select(RawOpportunity).where(RawOpportunity.status == RawStatus.pending.value)
    ).all()
    assert len(pending) == 2
    assert pending[0].raw_payload.get("certificate") is True  # per-source framing applied
    assert db.scalar(select(func.count(Opportunity.id))) == 0  # nothing auto-published


def test_auto_promote_true_publishes(db, monkeypatch):
    monkeypatch.setattr(RSSAdapter, "fetch", lambda self: list(ITEMS))
    src = _source(db, {"auto_promote": True, "trust_all_items": True})

    log = runner.ingest_source(db, src)
    assert log.items_promoted == 2
    assert db.scalar(select(func.count(Opportunity.id))) == 2

    # Re-ingesting the same feed stages nothing new (idempotent by external_id).
    log2 = runner.ingest_source(db, src)
    assert log2.items_new == 0
