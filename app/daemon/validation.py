"""Validation daemon cycle: ping live URLs, log, expire & disable dead links."""
from __future__ import annotations

import logging
import time
from datetime import timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    AlertType,
    Opportunity,
    Source,
    ValidationLog,
    ValidationResult,
    utcnow,
)
from ..pipeline.freshness import freshness_score, provider_health
from ..services.alerts import emit_alert

logger = logging.getLogger("veloxi.validation")


def _classify(code: int | None) -> ValidationResult:
    if code is None:
        return ValidationResult.connection_error
    if 200 <= code < 300:
        return ValidationResult.ok
    if 300 <= code < 400:
        return ValidationResult.redirect
    if 400 <= code < 500:
        return ValidationResult.client_error
    return ValidationResult.server_error


def _check_url(url: str) -> tuple[int | None, ValidationResult, int, str | None]:
    start = time.monotonic()
    try:
        with httpx.Client(
            timeout=settings.request_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": settings.http_user_agent},
        ) as client:
            try:
                resp = client.head(url)
                if resp.status_code >= 400:  # many sites reject HEAD
                    resp = client.get(url)
            except httpx.HTTPError:
                resp = client.get(url)
        latency = int((time.monotonic() - start) * 1000)
        return resp.status_code, _classify(resp.status_code), latency, None
    except httpx.TimeoutException as exc:
        return None, ValidationResult.timeout, int((time.monotonic() - start) * 1000), str(exc)[:400]
    except Exception as exc:
        return None, ValidationResult.connection_error, int((time.monotonic() - start) * 1000), str(exc)[:400]


def validate_cycle(session: Session, batch_size: int | None = None) -> dict:
    """Run one validation pass. Returns a small summary dict."""
    now = utcnow()
    batch_size = batch_size or settings.validation_batch_size

    # 1) Expire anything past its deadline.
    expired = session.scalars(
        select(Opportunity).where(
            Opportunity.is_active.is_(True),
            Opportunity.is_expired.is_(False),
            Opportunity.expires_at.is_not(None),
            Opportunity.expires_at < now,
        )
    ).all()
    for o in expired:
        o.is_expired = True
        o.is_active = False
        o.freshness_score = 0
        emit_alert(session, AlertType.scholarship_closing, f"Opportunity expired: {o.title}", opportunity=o)

    # 2) Flag deadlines within 7 days.
    soon = session.scalars(
        select(Opportunity).where(
            Opportunity.is_active.is_(True),
            Opportunity.expires_at.is_not(None),
            Opportunity.expires_at >= now,
            Opportunity.expires_at <= now + timedelta(days=7),
        )
    ).all()
    for o in soon:
        emit_alert(
            session,
            AlertType.deadline_approaching,
            f"Deadline approaching for {o.title}",
            opportunity=o,
            payload={"expires_at": o.expires_at.isoformat()},
        )

    # 3) Ping a batch, oldest-verified first (NULLs sort first on SQLite ASC).
    rows = session.scalars(
        select(Opportunity)
        .where(Opportunity.is_active.is_(True), Opportunity.is_expired.is_(False))
        .order_by(Opportunity.last_verified_at.asc())
        .limit(batch_size)
    ).all()

    checked = deactivated = 0
    for o in rows:
        code, result, latency, message = _check_url(o.url)
        session.add(
            ValidationLog(
                opportunity_id=o.id,
                status_code=code,
                result=result.value,
                latency_ms=latency,
                message=message,
            )
        )
        src = session.get(Source, o.source_id) if o.source_id else None
        if result in (ValidationResult.ok, ValidationResult.redirect):
            o.validation_fail_count = 0
            o.last_verified_at = utcnow()
            if src:
                src.health_score = min(100, src.health_score + 5)
                src.consecutive_failures = 0
        else:
            o.validation_fail_count += 1
            if src:
                src.health_score = max(0, src.health_score - 15)
            if o.validation_fail_count >= settings.validation_fail_threshold:
                o.is_active = False
                deactivated += 1
                emit_alert(
                    session,
                    AlertType.source_down,
                    f"Disabled dead link after repeated failures: {o.title}",
                    opportunity=o,
                    source=src,
                )

        health = src.health_score if src else provider_health(o.provider)
        o.freshness_score = freshness_score(
            last_verified_at=o.last_verified_at,
            published_at=o.published_at,
            created_at=o.created_at,
            source_health=health,
            is_active=o.is_active,
            is_expired=o.is_expired,
        )
        checked += 1

    session.commit()
    return {"checked": checked, "deactivated": deactivated, "expired": len(expired)}
