from app.ingest.rss import RSSAdapter
from app.models import Source, SourceType

FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Test Feed</title>
  <item>
    <title>Intro to Python</title>
    <link>https://example.com/python</link>
    <guid>guid-1</guid>
    <description>Learn Python from scratch.</description>
  </item>
  <item>
    <title>Cloud 101</title>
    <link>https://example.com/cloud</link>
    <guid>guid-2</guid>
  </item>
</channel></rss>"""


def test_rss_parse_extracts_items():
    source = Source(
        name="Test", type=SourceType.rss.value, url="https://example.com/rss",
        default_provider="Test Provider", config={"default_category": "Software Development"},
    )
    items = list(RSSAdapter(source).parse(FIXTURE))

    assert len(items) == 2
    first = items[0]
    assert first.title == "Intro to Python"
    assert first.url == "https://example.com/python"
    assert first.external_id == "guid-1"
    assert first.provider == "Test Provider"
    assert first.suggested_category == "Software Development"
