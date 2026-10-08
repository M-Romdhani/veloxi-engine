"""Probe a source for reachability (never raises)."""
from __future__ import annotations

import logging

import httpx

from ..config import settings
from ..models import Source, SourceStatus, SourceType, utcnow

logger = logging.getLogger("veloxi.verify")


def probe_source(source: Source) -> str:
    """Return a SourceStatus value and update probe bookkeeping on ``source``."""
    source.last_probed_at = utcnow()

    if source.type == SourceType.manual.value:
        source.status = SourceStatus.verified.value
        source.consecutive_failures = 0
        source.health_score = min(100, source.health_score + 5)
        return source.status

    if not source.url:
        source.status = SourceStatus.unreachable.value
        return source.status

    try:
        resp = httpx.get(
            source.url,
            timeout=settings.request_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": settings.http_user_agent},
        )
        ok = resp.status_code < 400
        if ok and source.type == SourceType.rss.value:
            from ..ingest.rss import parse_feed

            ok = bool(parse_feed(resp.content)[1])
        if ok:
            source.status = SourceStatus.verified.value
            source.consecutive_failures = 0
            source.health_score = min(100, source.health_score + 5)
        else:
            _mark_failure(source)
    except Exception as exc:  # network failures must not propagate
        logger.info("probe failed for source %s: %s", source.id, exc)
        _mark_failure(source)

    return source.status


def _mark_failure(source: Source) -> None:
    source.status = SourceStatus.unreachable.value
    source.consecutive_failures += 1
    source.health_score = max(0, source.health_score - 25)
