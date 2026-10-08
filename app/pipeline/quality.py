"""Opportunity quality scoring + blended ranking.

Freshness alone is a weak ranking signal: ``provider_health`` in
``freshness.py`` is a *hash* of the provider name, so a no-name blog can
outrank Google. This module adds a curated **provider-trust** signal and a
**quality score** (provider trust + certificate + audit + a freshness
contribution), then a blended rank:

    rank = 0.5·quality + 0.3·freshness + 0.2·relevance  (+ deadline urgency)

Everything here is computed on the fly from existing ``Opportunity`` columns
— no new DB column, so no migration is needed on the live database.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone

# --------------------------------------------------------------------------- #
# Provider trust (0..100). Curated, not a hash — trusted names rank higher.
# --------------------------------------------------------------------------- #
PROVIDER_TRUST: dict[str, int] = {
    # Big tech / first-party platforms
    "google": 95, "google cloud": 93, "microsoft": 92, "aws": 92,
    "amazon": 88, "amazon web services": 92, "meta": 88, "ibm": 88,
    "apple": 90, "nvidia": 90, "adobe": 86,
    # Top universities / academia
    "harvard": 95, "harvard business school": 92, "stanford": 94, "yale": 92,
    "mit": 95, "massachusetts institute of technology": 95, "caltech": 93,
    "calarts": 84, "uc san diego": 86, "duke university": 85,
    "gates cambridge": 90,
    # Course platforms & publishers
    "coursera": 85, "edx": 88, "futurelearn": 82, "udacity": 78,
    "datacamp": 80, "codecademy": 76, "linkedin learning": 80, "linkedin": 80,
    "deeplearning.ai": 90, "fast.ai": 82, "kaggle": 85, "freecodecamp": 80,
    "the odin project": 75, "domestika": 70, "interaction design foundation": 80,
    "figma": 82, "canva": 72,
    # Vendor / professional certification bodies
    "cisco": 86, "comptia": 85, "isc2": 86, "(isc)²": 86, "ec-council": 80,
    "pmi": 84, "linux foundation": 88, "hashicorp": 84, "fortinet": 84,
    "tryhackme": 80, "portswigger": 84, "open university": 82,
    # Scholarship / fellowship bodies
    "uk government": 88, "daad": 86, "fulbright": 88, "erasmus+": 86,
    "erasmus": 86, "mastercard foundation": 82, "chevening": 88,
    # Job boards / aggregators (legit but not course providers)
    "eures": 80, "we work remotely": 65, "dribbble": 72,
    "ai-jobs.net": 60, "infosec-jobs.com": 60,
}

_DEFAULT_TRUST = 50  # unknown but plausible
_UNIVERSITY_TRUST = 82  # any "University of …" / college / institute
_GOVERNMENT_TRUST = 85  # government / EU commission bodies


def provider_trust(provider: str | None) -> int:
    """Curated trust for a provider name (0..100); ~50 when unknown."""
    if not provider:
        return _DEFAULT_TRUST
    key = provider.strip().lower()
    if key in PROVIDER_TRUST:
        return PROVIDER_TRUST[key]
    # Substring match for compound names (skip very short keys to avoid
    # accidental hits like "mit" inside "submit").
    for name, score in PROVIDER_TRUST.items():
        if len(name) >= 4 and name in key:
            return score
    if any(w in key for w in ("university", "college", "institute", "school of")):
        return _UNIVERSITY_TRUST
    if any(w in key for w in ("government", "commission", "ministry")):
        return _GOVERNMENT_TRUST
    return _DEFAULT_TRUST


# --------------------------------------------------------------------------- #
# Quality score
# --------------------------------------------------------------------------- #
def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def quality_score(o) -> int:
    """Blend provider trust, certificate, audit, and freshness into 0..100.

    Examples: Google cert (fresh) -> ~88-93; an unknown blog -> ~35-50.
    ``rating`` is intentionally absent — reserved for when a ratings feed
    exists; the formula already separates trusted from untrusted sources.
    """
    trust = provider_trust(getattr(o, "provider", None))
    fresh = float(getattr(o, "freshness_score", 0) or 0)
    cert = 12 if getattr(o, "certificate", False) else 0
    audit = 5 if getattr(o, "audit", False) else 0
    return int(round(_clamp(0.65 * trust + cert + audit + 0.18 * fresh)))


# --------------------------------------------------------------------------- #
# Deadlines (derived from expires_at — no new column)
# --------------------------------------------------------------------------- #
def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def days_remaining(expires_at: datetime | None, now: datetime | None = None) -> int | None:
    """Whole days until ``expires_at`` (rounded up), or None if no deadline.

    0 means closing today / already past; the public list excludes expired rows.
    """
    expires_at = _aware(expires_at)
    if expires_at is None:
        return None
    now = now or datetime.now(timezone.utc)
    seconds = (expires_at - now).total_seconds()
    if seconds <= 0:
        return 0
    return math.ceil(seconds / 86400.0)


def deadline_boost(o, now: datetime | None = None) -> float:
    """Small ranking nudge so near-deadline scholarships surface first."""
    d = days_remaining(getattr(o, "expires_at", None), now=now)
    if d is None:
        return 0.0
    if d <= 7:
        return 0.06
    if d <= 14:
        return 0.04
    if d <= 30:
        return 0.02
    return 0.0


# --------------------------------------------------------------------------- #
# Relevance + blended rank
# --------------------------------------------------------------------------- #
_STOP = {"the", "a", "an", "to", "for", "of", "in", "and", "or", "with", "i", "want", "learn", "get"}


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9+]+", (text or "").lower()) if t and t not in _STOP}


def relevance(query: str | None, o) -> float:
    """Fraction of query tokens present in the opportunity's text (0..1).

    Includes the skills the opportunity teaches, so a goal like "tableau"
    matches a course tagged with that skill even if the word isn't in the title.
    """
    qt = _tokens(query or "")
    if not qt:
        return 0.0
    skills = " ".join(s.name for s in (getattr(o, "skills", None) or []))
    hay = _tokens(
        f"{getattr(o, 'title', '')} {getattr(o, 'category', '')} "
        f"{getattr(o, 'description', '') or ''} {' '.join(getattr(o, 'tags', None) or [])} {skills}"
    )
    return len(qt & hay) / len(qt)


def rank_score(o, query: str | None = None, now: datetime | None = None) -> float:
    """Blended 0..1 rank: 0.5·quality + 0.3·freshness + 0.2·relevance + urgency."""
    q = quality_score(o) / 100.0
    f = float(getattr(o, "freshness_score", 0) or 0) / 100.0
    r = relevance(query, o)
    return min(1.0, 0.5 * q + 0.3 * f + 0.2 * r + deadline_boost(o, now=now))
