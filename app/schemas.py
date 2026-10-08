"""Pydantic request/response models for the admin API."""
from __future__ import annotations

from pydantic import BaseModel


class SourceIn(BaseModel):
    name: str
    type: str  # rss | api | scraper | manual
    url: str | None = None
    config: dict = {}
    default_provider: str | None = None
    is_enabled: bool = True


class SourceUpdate(BaseModel):
    name: str | None = None
    url: str | None = None
    config: dict | None = None
    default_provider: str | None = None
    is_enabled: bool | None = None


class ManualOpportunityIn(BaseModel):
    title: str
    provider: str
    url: str
    category: str | None = None
    kind: str | None = None  # course | job | scholarship (inferred if omitted)
    difficulty: str | None = None
    cost: float = 0
    audit: bool = False
    certificate: bool = False
    duration: str = "Self-paced"
    description: str | None = None
    tags: list[str] = []
    expires_at: str | None = None
    approve: bool = True  # promote immediately vs. leave in the approval queue


class RejectIn(BaseModel):
    reason: str | None = None


class CareerAnalyzeIn(BaseModel):
    cv_text: str
    goal: str | None = None
    category: str | None = None
