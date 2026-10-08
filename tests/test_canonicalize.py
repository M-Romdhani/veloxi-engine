from app.pipeline.canonicalize import canonical_url

CASES = [
    ("https://www.coursera.org/learn/x/", "https://coursera.org/learn/x"),
    ("http://Coursera.org/learn/x", "https://coursera.org/learn/x"),
    (
        "https://coursera.org/learn/x?utm_source=a&utm_medium=b#syllabus",
        "https://coursera.org/learn/x",
    ),
    (
        "https://m.example.com/a//b/?gclid=123&q=python",
        "https://example.com/a/b?q=python",
    ),
    ("coursera.org/learn/x", "https://coursera.org/learn/x"),
]


def test_canonicalize_cases():
    for raw, expected in CASES:
        assert canonical_url(raw) == expected


def test_canonicalize_idempotent():
    for raw, _ in CASES:
        once = canonical_url(raw)
        assert canonical_url(once) == once


def test_query_params_sorted():
    assert canonical_url("https://x.com/p?b=2&a=1") == "https://x.com/p?a=1&b=2"
