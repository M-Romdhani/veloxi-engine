"""RSS/Atom adapter (functional) — standard-library XML parsing.

Handles both RSS 2.0 (<channel><item>) and Atom (<feed><entry>) by matching on
local element names, so no third-party feed dependency is needed.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime

import httpx
from dateutil import parser as dtparser

from ..config import settings
from ..models import SourceType
from .base import AdapterRegistry, RawItem, SourceAdapter


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _entry_dict(item: ET.Element) -> dict:
    data = {"title": None, "link": None, "id": None, "summary": None, "published": None}
    for child in item:
        name = _local(child.tag)
        if name == "title" and not data["title"]:
            data["title"] = (child.text or "").strip()
        elif name == "link":
            href = child.get("href")  # Atom style
            if href:
                rel = child.get("rel")
                if rel in (None, "alternate") or not data["link"]:
                    data["link"] = href.strip()
            elif child.text and child.text.strip():
                data["link"] = child.text.strip()
        elif name in ("guid", "id") and not data["id"]:
            data["id"] = (child.text or "").strip()
        elif name in ("summary", "description", "content") and not data["summary"]:
            data["summary"] = (child.text or "").strip()
        elif name in ("published", "pubdate", "updated") and not data["published"]:
            data["published"] = (child.text or "").strip()
    return data


def parse_feed(content: bytes) -> tuple[str | None, list[dict]]:
    """Return (feed_title, [entry dicts]). Empty list on unparseable input."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return None, []

    container = root
    if _local(root.tag) == "rss":
        channel = next((c for c in root if _local(c.tag) == "channel"), None)
        if channel is not None:
            container = channel

    feed_title = None
    for child in list(container):
        if _local(child.tag) == "title":
            feed_title = (child.text or "").strip()
            break

    entries = [_entry_dict(el) for el in container if _local(el.tag) in ("item", "entry")]
    return feed_title, entries


def _to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return dtparser.parse(value)
    except (ValueError, OverflowError, TypeError):
        return None


@AdapterRegistry.register
class RSSAdapter(SourceAdapter):
    type = SourceType.rss.value

    def fetch(self):
        resp = httpx.get(
            self.source.url,
            timeout=settings.request_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": settings.http_user_agent},
        )
        resp.raise_for_status()
        return list(self.parse(resp.content))

    def parse(self, content: bytes):
        """Parse feed bytes into RawItems (no network — used by tests too)."""
        feed_title, entries = parse_feed(content)
        cfg = self.source.config or {}
        for entry in entries:
            link = entry.get("link")
            if not link:
                continue
            yield RawItem(
                title=(entry.get("title") or "").strip() or link,
                url=link,
                external_id=entry.get("id") or link,
                description=entry.get("summary"),
                provider=self.source.default_provider or feed_title,
                suggested_category=cfg.get("default_category"),
                published_at=_to_dt(entry.get("published")),
                raw_payload={"title": entry.get("title"), "link": link},
            )
