"""REAL ingestion sources for the seed.

Enabled by default: freeCodeCamp RSS (routed through the approval queue) and the
manual admin channel. The rest are realistic, ready-to-enable examples that show
the RSS / JSON-API / Apify / scraper config shapes — left disabled so nothing
hits the network until you opt in.
"""
from __future__ import annotations

from ..models import SourceType

REAL_SOURCES: list[dict] = [
    {
        "name": "freeCodeCamp News",
        "type": SourceType.rss.value,
        "url": "https://www.freecodecamp.org/news/rss/",
        "default_provider": "freeCodeCamp",
        "is_enabled": True,
        # RSS items carry only title/link/date, so we frame them as free, self-paced
        # tutorials and route them to the approval queue (auto_promote=false) so an
        # admin curates what reaches the public index.
        "config": {
            "default_category": "Software Development",
            "default_cost": 0,
            "default_certificate": False,
            "default_audit": False,
            "default_duration": "Self-paced",
            "default_tags": ["free", "tutorial"],
            "auto_promote": False,
        },
    },
    {
        "name": "Admin Submissions",
        "type": SourceType.manual.value,
        "url": None,
        "default_provider": None,
        "is_enabled": True,
        "config": {},
    },
    {
        # Real developer-learning feed (career/learning articles). Disabled here only
        # because this sandbox can't reach it; enable where dev.to is reachable.
        "name": "dev.to — Career (RSS, example)",
        "type": SourceType.rss.value,
        "url": "https://dev.to/feed/tag/career",
        "default_provider": "dev.to",
        "is_enabled": False,
        "config": {
            "default_category": "Software Development",
            "default_cost": 0,
            "default_duration": "Self-paced",
            "default_tags": ["free", "article"],
            "auto_promote": False,
        },
    },
    {
        # Real remote-jobs feed (career opportunities).
        "name": "We Work Remotely (RSS, example)",
        "type": SourceType.rss.value,
        "url": "https://weworkremotely.com/remote-jobs.rss",
        "default_provider": "We Work Remotely",
        "is_enabled": False,
        "config": {
            "default_category": "Software Development",
            "default_cost": 0,
            "default_duration": "Full-time role",
            "default_tags": ["remote", "job"],
            "auto_promote": False,
        },
    },
    {
        # Real JSON API returning a top-level array (no items_path needed).
        "name": "RemoteOK API (JSON, example)",
        "type": SourceType.api.value,
        "url": "https://remoteok.com/api",
        "default_provider": "RemoteOK",
        "is_enabled": False,
        "config": {
            "title_field": "position",
            "url_field": "url",
            "id_field": "id",
            "description_field": "description",
            "default_category": "Software Development",
            "default_cost": 0,
            "default_tags": ["remote", "job"],
            "auto_promote": False,
        },
    },
    {
        # First-class Apify source: runs an Actor and ingests its dataset.
        # Set APIFY_TOKEN (env) + config.actor_id, map fields to the actor's
        # output schema, then enable. (field names below are illustrative.)
        "name": "Apify — Remote Jobs (example)",
        "type": SourceType.apify.value,
        "url": None,
        "default_provider": "Apify",
        "is_enabled": False,
        "config": {
            "actor_id": "bebity~linkedin-jobs-scraper",
            "input": {"location": "Remote", "keywords": "developer", "rows": 25},
            "title_field": "title",
            "url_field": "jobUrl",
            "id_field": "id",
            "description_field": "description",
            "default_category": "Software Development",
            "default_kind": "job",
            "default_tags": ["remote", "job"],
            "auto_promote": False,
        },
    },
    {
        # Structured-scraper scaffold (configure selectors + implement parsing).
        "name": "Example Scraper (disabled)",
        "type": SourceType.scraper.value,
        "url": "https://example.com/opportunities",
        "default_provider": "Example",
        "is_enabled": False,
        "config": {
            "item_selector": ".opportunity",
            "title_selector": "h2",
            "url_selector": "a",
        },
    },
]
