from app.seed import load_seed


def test_opportunities_shape_and_filters(db, client):
    load_seed(db)

    res = client.get("/api/opportunities")
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) > 0

    item = rows[0]
    for key in (
        "id", "provider", "title", "category", "kind", "difficulty", "cost",
        "audit", "certificate", "duration", "freshnessLabel", "freshnessScore",
        "qualityScore", "url", "sourceUrl", "lastVerifiedAt", "expiresAt",
        "daysRemaining", "skills",
    ):
        assert key in item

    # Default order is quality-led: the top pick is a high-trust provider, and
    # (ignoring deadline-boosted scholarships) the quality+freshness blend is
    # non-increasing down the list.
    assert rows[0]["qualityScore"] >= 80
    blend = lambda r: 0.5 * r["qualityScore"] + 0.3 * r["freshnessScore"]
    blends = [blend(r) for r in rows if r["kind"] != "scholarship"]
    assert blends == sorted(blends, reverse=True)

    # free_only filter.
    free = client.get("/api/opportunities", params={"free_only": "true"}).json()
    assert all(r["cost"] == 0 for r in free)

    # category filter.
    cyber = client.get("/api/opportunities", params={"category": "Cybersecurity"}).json()
    assert cyber and all(r["category"] == "Cybersecurity" for r in cyber)

    # certificate_only filter.
    certs = client.get("/api/opportunities", params={"certificate_only": "true"}).json()
    assert all(r["certificate"] is True for r in certs)


def test_kind_filter(db, client):
    load_seed(db)
    scholarships = client.get("/api/opportunities", params={"kind": "scholarship"}).json()
    assert len(scholarships) >= 6
    assert all(r["kind"] == "scholarship" for r in scholarships)
    assert all(r["expiresAt"] for r in scholarships)  # deadlines set
    assert all(r["daysRemaining"] is not None for r in scholarships)

    courses = client.get("/api/opportunities", params={"kind": "course"}).json()
    assert courses and all(r["kind"] == "course" for r in courses)

    jobs = client.get("/api/opportunities", params={"kind": "job"}).json()
    assert len(jobs) >= 5 and all(r["kind"] == "job" for r in jobs)


def test_providers_listing_and_filter(db, client):
    load_seed(db)

    providers = client.get("/api/providers").json()
    assert providers, "expected at least one provider"
    assert all(p["name"] and p["count"] >= 1 for p in providers)
    # Busiest first.
    counts = [p["count"] for p in providers]
    assert counts == sorted(counts, reverse=True)

    # Filtering by a provider returns only that provider's opportunities.
    name = providers[0]["name"]
    rows = client.get("/api/opportunities", params={"provider": name}).json()
    assert rows and all(r["provider"] == name for r in rows)


def test_categories_and_stats(db, client):
    load_seed(db)
    cats = client.get("/api/categories").json()
    from app.models import CATEGORIES, CATEGORY_GROUPS
    assert len(cats) == len(CATEGORIES)
    assert sum(c["count"] for c in cats) > 0
    # Every category is tagged with its section for grouped filters.
    assert {c["group"] for c in cats} == set(CATEGORY_GROUPS)

    stats = client.get("/api/stats").json()
    assert stats["activeOpportunities"] > 0


def test_recommendations_are_explainable(db, client):
    load_seed(db)
    recs = client.get("/api/recommendations", params={"goal": "cybersecurity"}).json()
    assert len(recs) > 0
    assert all("explanation" in r for r in recs)
    assert any("cybersecurity" in r["explanation"].lower() for r in recs)


def test_admin_requires_token(db, client):
    assert client.get("/admin/sources").status_code == 401
    ok = client.get("/admin/sources", headers={"X-Admin-Token": "test-token"})
    assert ok.status_code == 200






def test_admin_reseed(client):
    r = client.post("/admin/reseed", headers={"X-Admin-Token": "test-token"})
    assert r.status_code == 200
    assert "opportunities_created" in r.json()


def test_delete_source_unlinks_opportunities(db, client):
    # Deleting a source must not 500 when opportunities reference it; the
    # listings survive (unlinked) while the source is removed.
    from app.models import Opportunity, Source

    s = Source(name="Temp Feed", type="manual")
    db.add(s)
    db.commit()
    db.refresh(s)
    o = Opportunity(
        provider="X", title="Linked listing", category="Design",
        url="https://x.example/job", canonical_url="https://x.example/job",
        source_id=s.id,
    )
    db.add(o)
    db.commit()
    oid = o.id

    r = client.delete(f"/admin/sources/{s.id}", headers={"X-Admin-Token": "test-token"})
    assert r.status_code == 204

    db.expunge_all()
    kept = db.get(Opportunity, oid)
    assert kept is not None and kept.source_id is None
    assert db.get(Source, s.id) is None


def test_root_and_health(client):
    assert client.get("/").json()["docs"] == "/docs"
    assert client.get("/health").json()["status"] == "ok"


def test_admin_locked_without_configured_token(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "admin_token", "")
    assert client.get("/admin/sources", headers={"X-Admin-Token": ""}).status_code == 503
