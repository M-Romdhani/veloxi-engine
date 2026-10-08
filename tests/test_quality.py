"""Unit tests for the quality score, blended rank, and deadline helpers."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.pipeline.quality import (
    days_remaining,
    provider_trust,
    quality_score,
    rank_score,
)


def _opp(**kw):
    base = dict(
        provider="Unknown Blog", title="t", category="Data & AI", description="",
        tags=[], certificate=False, audit=False, freshness_score=50,
        expires_at=None, kind="course",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_trusted_provider_outranks_unknown():
    assert provider_trust("Google") > provider_trust("Some Random Blog")
    # "University of …" names get the academic trust floor.
    assert provider_trust("University of Helsinki") >= 80

    good = quality_score(_opp(provider="Google", certificate=True, freshness_score=80))
    weak = quality_score(_opp(provider="Some Random Blog", certificate=False, freshness_score=80))
    assert good > weak
    assert good >= 85 and weak <= 55


def test_quality_leads_ranking():
    # A trusted, certified course outranks a *fresher* no-name blog: quality is
    # weighted highest (0.5), so it overcomes a reasonable freshness deficit.
    trusted = _opp(provider="Google", certificate=True, freshness_score=60)
    fresher_blog = _opp(provider="Some Random Blog", certificate=False, freshness_score=80)
    assert rank_score(trusted) > rank_score(fresher_blog)


def test_relevance_lifts_matching_results():
    o = _opp(provider="Google", title="Cybersecurity Analyst", category="Cybersecurity")
    assert rank_score(o, "cybersecurity") > rank_score(o, "gardening")


def test_days_remaining_and_deadline_urgency():
    now = datetime.now(timezone.utc)
    assert days_remaining(None) is None
    assert days_remaining(now + timedelta(days=3)) == 3
    assert days_remaining(now - timedelta(days=1)) == 0  # past => closing today

    soon = _opp(provider="X", kind="scholarship", expires_at=now + timedelta(days=3))
    later = _opp(provider="X", kind="scholarship", expires_at=now + timedelta(days=300))
    assert rank_score(soon) > rank_score(later)  # near-deadline gets a nudge
