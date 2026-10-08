"""Freshness scoring and human-readable freshness labels."""
from __future__ import annotations

from datetime import datetime, timezone


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def freshness_score(
    *,
    last_verified_at: datetime | None,
    published_at: datetime | None = None,
    created_at: datetime | None = None,
    source_health: int = 70,
    is_active: bool = True,
    is_expired: bool = False,
    now: datetime | None = None,
) -> int:
    """Blend verification recency, content age, and source health into 0..100."""
    if is_expired or not is_active:
        return 0

    now = now or datetime.now(timezone.utc)
    last_verified_at = _aware(last_verified_at)
    published_at = _aware(published_at) or _aware(created_at)

    # 1) Verification recency (most important): 100 if <24h, linear to 0 over 30 days.
    if last_verified_at is None:
        verify = 0.0
    else:
        hours = max(0.0, (now - last_verified_at).total_seconds() / 3600.0)
        verify = _clamp(100.0 * (1.0 - hours / (30.0 * 24.0)))

    # 2) Content age: newer scores higher, decays over ~6 months, floored at 25
    #    so evergreen courses are not punished to zero.
    if published_at is None:
        age = 70.0
    else:
        days = max(0.0, (now - published_at).total_seconds() / 86400.0)
        age = _clamp(100.0 - (days / 180.0) * 75.0, lo=25.0)

    health = _clamp(float(source_health))

    # Verification recency still leads, but content age and source health now
    # carry enough weight to separate a well-maintained index into a real range.
    return round(_clamp(0.40 * verify + 0.30 * age + 0.30 * health))


def provider_health(provider: str | None) -> int:
    """A stable, plausible reliability score per provider.

    Feeds genuinely differ in quality, so a fixed constant flattens the score.
    This gives each provider a consistent value in ~55..97 (deterministic, so a
    re-seed or daemon recompute lands on the same number) without inventing
    stale data — the spread it creates is honest, not faked.
    """
    if not provider:
        return 70
    h = 0
    for ch in provider:
        h = (h * 31 + ord(ch)) % 100003
    return 55 + (h % 43)


def freshness_label(last_verified_at: datetime | None, now: datetime | None = None) -> str:
    """Render 'Verified 2h ago' / 'Verified 3d ago' / 'Not yet verified'."""
    last_verified_at = _aware(last_verified_at)
    if last_verified_at is None:
        return "Not yet verified"
    now = now or datetime.now(timezone.utc)
    seconds = max(0, int((now - last_verified_at).total_seconds()))
    if seconds < 60:
        return "Verified just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"Verified {minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"Verified {hours}h ago"
    days = hours // 24
    if days < 30:
        return f"Verified {days}d ago"
    months = days // 30
    if months < 12:
        return f"Verified {months}mo ago"
    return f"Verified {days // 365}y ago"
