"""Adapter interface + registry. Sources map to adapters by their ``type``."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from ..models import Source


@dataclass
class RawItem:
    title: str
    url: str
    external_id: str | None = None
    description: str | None = None
    provider: str | None = None
    suggested_category: str | None = None
    published_at: datetime | None = None
    raw_payload: dict = field(default_factory=dict)


class SourceAdapter(ABC):
    type: ClassVar[str]

    def __init__(self, source: Source):
        self.source = source

    @abstractmethod
    def fetch(self) -> Iterable[RawItem]:
        """Pull items from the source. May hit the network; raises on hard failure."""


class AdapterRegistry:
    _by_type: dict[str, type[SourceAdapter]] = {}

    @classmethod
    def register(cls, adapter_cls: type[SourceAdapter]) -> type[SourceAdapter]:
        cls._by_type[adapter_cls.type] = adapter_cls
        return adapter_cls

    @classmethod
    def for_source(cls, source: Source) -> SourceAdapter:
        try:
            return cls._by_type[source.type](source)
        except KeyError as exc:
            raise ValueError(f"No adapter registered for source type {source.type!r}") from exc


def map_records(records, cfg: dict, default_provider: str | None = None) -> list[RawItem]:
    """Map a list of JSON dicts to RawItems using config field mappings.

    Shared by the JSON-API and Apify adapters. ``cfg`` keys: title_field,
    url_field, id_field, description_field, default_category.
    """
    cfg = cfg or {}
    title_f = cfg.get("title_field", "title")
    url_f = cfg.get("url_field", "url")
    id_f = cfg.get("id_field", "id")
    desc_f = cfg.get("description_field")
    items: list[RawItem] = []
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        url = rec.get(url_f)
        title = rec.get(title_f)
        if not url or not title:
            continue
        items.append(
            RawItem(
                title=str(title).strip(),
                url=str(url),
                external_id=str(rec.get(id_f) or url),
                description=str(rec.get(desc_f)) if desc_f and rec.get(desc_f) else None,
                provider=default_provider,
                suggested_category=cfg.get("default_category"),
                raw_payload=rec,
            )
        )
    return items
