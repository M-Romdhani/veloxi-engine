"""JSON API adapter — config-driven; runs against any JSON endpoint."""
from __future__ import annotations

import httpx

from ..config import settings
from ..models import SourceType
from .base import AdapterRegistry, SourceAdapter, map_records


@AdapterRegistry.register
class JsonApiAdapter(SourceAdapter):
    type = SourceType.api.value

    def fetch(self):
        cfg = self.source.config or {}
        items_path = cfg.get("items_path")
        resp = httpx.get(
            self.source.url,
            timeout=settings.request_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": settings.http_user_agent},
        )
        resp.raise_for_status()

        data = resp.json()
        if items_path:
            for key in items_path.split("."):
                if isinstance(data, dict):
                    data = data.get(key, [])
        elif not isinstance(data, list):
            raise NotImplementedError(
                "Configure this API source: set config.items_path (dotted path to the "
                "list), or point it at an endpoint that returns a top-level JSON array. "
                "Also set title_field/url_field (and optionally id_field, "
                "description_field, default_category)."
            )
        return map_records(data, cfg, self.source.default_provider)
