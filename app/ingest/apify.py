"""Apify adapter — run an Actor and ingest its dataset items.

Calls the Actor's ``run-sync-get-dataset-items`` endpoint, which runs the actor
and returns its dataset as a top-level JSON array. Token comes from
``APIFY_TOKEN`` (env) or ``config.token``; the actor id and optional input come
from ``config``. Field mapping reuses the shared JSON mapper.

Config keys:
  actor_id           e.g. "apify/website-content-crawler" or "bebity~linkedin-jobs-scraper"
  input              (optional) dict of Actor input -> sent as the POST body
  token              (optional) overrides APIFY_TOKEN
  title_field/url_field/id_field/description_field/default_category   field mapping
"""
from __future__ import annotations

import httpx

from ..config import settings
from ..models import SourceType
from .base import AdapterRegistry, SourceAdapter, map_records


@AdapterRegistry.register
class ApifyAdapter(SourceAdapter):
    type = SourceType.apify.value

    def fetch(self):
        cfg = self.source.config or {}
        token = cfg.get("token") or settings.apify_token
        actor = cfg.get("actor_id") or _actor_from_url(self.source.url)
        if not token:
            raise NotImplementedError("Set APIFY_TOKEN (env) or config.token for this Apify source.")
        if not actor:
            raise NotImplementedError("Set config.actor_id (e.g. 'apify/website-content-crawler').")

        # Apify accepts '/' or '~' as the owner/name separator; the API wants '~'.
        actor_path = actor.replace("/", "~")
        url = (
            f"https://api.apify.com/v2/acts/{actor_path}/run-sync-get-dataset-items"
            f"?token={token}"
        )
        actor_input = cfg.get("input")
        headers = {"User-Agent": settings.http_user_agent}

        # Run-sync can take a while; use the longer Apify timeout.
        if actor_input:
            resp = httpx.post(url, json=actor_input, timeout=settings.apify_timeout_seconds, headers=headers)
        else:
            resp = httpx.get(url, timeout=settings.apify_timeout_seconds, follow_redirects=True, headers=headers)
        resp.raise_for_status()

        data = resp.json()
        if not isinstance(data, list):
            data = data.get("items", []) if isinstance(data, dict) else []
        return map_records(data, cfg, self.source.default_provider)


def _actor_from_url(url: str | None) -> str | None:
    if not url:
        return None
    # Pull the actor id out of a full .../acts/<actor>/... URL if provided.
    parts = url.split("/acts/", 1)
    if len(parts) == 2:
        return parts[1].split("/")[0].split("?")[0]
    return None
