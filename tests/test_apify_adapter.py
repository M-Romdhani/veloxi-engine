import httpx
import pytest

from app.ingest.apify import ApifyAdapter
from app.models import Source, SourceType

DATASET = [
    {"id": "j1", "title": "Backend Engineer", "jobUrl": "https://example.com/j1", "description": "Python role"},
    {"id": "j2", "title": "Data Analyst", "jobUrl": "https://example.com/j2"},
    {"note": "no title/url -> skipped"},
]


class _Resp:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return DATASET


def test_apify_maps_dataset(monkeypatch):
    captured = {}

    def fake_get(url, **kw):
        captured["url"] = url
        return _Resp()

    monkeypatch.setattr(httpx, "get", fake_get)
    src = Source(
        name="Apify", type=SourceType.apify.value, url=None, default_provider="Apify",
        config={
            "actor_id": "acme/jobs", "token": "tok",
            "title_field": "title", "url_field": "jobUrl",
            "id_field": "id", "description_field": "description",
        },
    )
    items = list(ApifyAdapter(src).fetch())

    assert len(items) == 2
    assert items[0].title == "Backend Engineer"
    assert items[0].url == "https://example.com/j1"
    assert items[0].external_id == "j1"
    assert "acme~jobs" in captured["url"]  # owner/name separator normalized to '~'
    assert "token=tok" in captured["url"]


def test_apify_requires_token_and_actor():
    # No token configured (and APIFY_TOKEN unset in tests) -> clear error.
    src = Source(name="Apify", type=SourceType.apify.value, url=None, config={"actor_id": "a/b"})
    with pytest.raises(NotImplementedError):
        list(ApifyAdapter(src).fetch())
