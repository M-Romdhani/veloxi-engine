from types import SimpleNamespace

from app.pipeline.opportunity_filter import looks_like_opportunity


def _item(title):
    return SimpleNamespace(title=title)


def test_drops_blog_articles():
    for title in (
        "How to Preprocess Medical Images for Machine Learning",
        "Backend Challenges Teams Face When Processing Repeat Payments",
        "Stop Trusting AI Code Blindly: A React Refactoring Case Study",
        "Why Production-Ready Actually Means in Flutter",
    ):
        assert looks_like_opportunity(_item(title)) is False


def test_keeps_real_opportunities():
    for title in (
        "Google Data Analytics Professional Certificate",
        "AWS Cloud Practitioner Course",
        "Chevening Scholarships 2026",
        "Software Engineer Internship Program",
    ):
        assert looks_like_opportunity(_item(title)) is True


def test_trusted_feed_keeps_role_titles_but_drops_newsletters():
    job_board = SimpleNamespace(config={"default_kind": "job"})
    # A role-name title has no keyword, but a vouched job board keeps it.
    assert looks_like_opportunity(_item("Senior Backend Engineer at Acme"), job_board) is True
    assert looks_like_opportunity(_item("Weekly roundup of remote jobs"), job_board) is False
