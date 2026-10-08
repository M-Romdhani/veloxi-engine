from datetime import datetime, timedelta, timezone

from app.pipeline.freshness import freshness_label, freshness_score

NOW = datetime(2026, 6, 3, tzinfo=timezone.utc)


def test_fresh_beats_stale():
    fresh = freshness_score(
        last_verified_at=NOW - timedelta(hours=1),
        published_at=NOW - timedelta(days=1),
        source_health=85,
        now=NOW,
    )
    stale = freshness_score(
        last_verified_at=NOW - timedelta(days=20),
        published_at=NOW - timedelta(days=1),
        source_health=85,
        now=NOW,
    )
    assert fresh > stale
    assert fresh >= 80


def test_monotonic_in_recency():
    scores = [
        freshness_score(last_verified_at=NOW - timedelta(days=d), source_health=70, now=NOW)
        for d in (0, 5, 15, 29)
    ]
    assert scores == sorted(scores, reverse=True)


def test_expired_is_zero():
    assert (
        freshness_score(last_verified_at=NOW, is_expired=True, now=NOW) == 0
    )
    assert freshness_score(last_verified_at=NOW, is_active=False, now=NOW) == 0


def test_labels():
    assert freshness_label(None) == "Not yet verified"
    assert freshness_label(NOW - timedelta(hours=2), now=NOW) == "Verified 2h ago"
    assert freshness_label(NOW - timedelta(days=3), now=NOW) == "Verified 3d ago"
