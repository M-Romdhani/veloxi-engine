import httpx

from app.ingest.api_json import JsonApiAdapter
from app.models import Source, SourceType

PAYLOAD = [
    {"id": 1, "position": "Backend Engineer", "url": "https://jobs.example.com/1", "description": "Python role"},
    {"id": 2, "position": "Data Analyst", "url": "https://jobs.example.com/2"},
    {"legal": "this row has no title/url and is skipped"},
]


class _FakeResp:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return PAYLOAD


def test_json_api_accepts_top_level_array(monkeypatch):
    # Apify's run-sync-get-dataset-items and APIs like RemoteOK return a bare array.
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResp())
    src = Source(
        name="Jobs API", type=SourceType.api.value, url="https://api.example.com/jobs",
        config={"title_field": "position", "url_field": "url", "id_field": "id", "description_field": "description"},
    )
    items = list(JsonApiAdapter(src).fetch())

    assert len(items) == 2  # the row without title/url is skipped
    assert items[0].title == "Backend Engineer"
    assert items[0].url == "https://jobs.example.com/1"
    assert items[0].external_id == "1"
    assert items[0].description == "Python role"
