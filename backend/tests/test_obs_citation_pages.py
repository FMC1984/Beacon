"""Top citation pages with "mentioned on page", and topic rankings (Phase 19)."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.models import AICitation, AICitedPage, AIPropertyObservation, Competitor, Mention, Property
from app.models.mention import ENTITY_COMPETITOR
from app.services.observatory.citation_pages import (
    MENTIONED,
    NOT_MENTIONED,
    UNCHECKED,
    UNREACHABLE,
    check_cited_pages,
    top_citation_pages,
)
from app.services.observatory.demo_seed import build_sample_portfolio, remove_sample_portfolio
from app.services.observatory.topic_rankings import _rank, topic_rankings

NOW = datetime(2026, 9, 10, 12, 0)
TODAY = NOW.date()


def _seeded(db):
    build_sample_portfolio(db, now=NOW, weeks=4)
    maple = db.query(Property).filter_by(name="Maple Ridge Flats").one()
    return maple


def test_citation_pages_reconcile_and_states_are_honest(db):
    maple = _seeded(db)
    out = top_citation_pages(db, maple.id, days=28, today=TODAY)
    assert out["data_label"] == "OBSERVED" and out["mention_check_label"] == "MEASURED"
    assert out["pages"], "sample portfolio should cite pages"
    rids = {r for (r,) in db.query(AIPropertyObservation.response_id).filter_by(property_id=maple.id, eligible=True)}
    raw = db.query(AICitation).filter(AICitation.response_id.in_(rids)).count()
    assert out["total_citations"] == raw
    assert sum(p["citations"] for p in out["pages"]) <= raw
    assert abs(sum(p["share"] for p in out["pages"]) - 1) < 0.02 or out["distinct_pages"] > len(out["pages"])
    states = {p["mentioned_on_page"] for p in out["pages"]}
    assert MENTIONED in states, "the property's own pages name it"
    assert states <= {MENTIONED, NOT_MENTIONED, UNCHECKED, UNREACHABLE}
    own = [p for p in out["pages"] if p["source_type"] == "owned"]
    assert own and all(p["mentioned_on_page"] == MENTIONED for p in own)
    for p in out["pages"]:
        if p["mentioned_on_page"] == NOT_MENTIONED:
            row = db.query(AICitedPage).filter_by(normalized_url=p["normalized_url"]).one()
            assert row.status == "ok", "never 'not mentioned' without a readable page"
        if p["mentioned_on_page"] == UNREACHABLE:
            assert p["mention_detail"]
    assert sum(out["check"].values()) == out["distinct_pages"]


def test_unreachable_never_reads_as_not_mentioned(db):
    maple = _seeded(db)
    page = next(p for p in top_citation_pages(db, maple.id, days=28, today=TODAY)["pages"] if p["mentioned_on_page"] == MENTIONED)
    row = db.query(AICitedPage).filter_by(normalized_url=page["normalized_url"]).one()
    row.status, row.error, row.body = "unreachable", "timed out", None
    db.commit()
    again = next(p for p in top_citation_pages(db, maple.id, days=28, today=TODAY)["pages"] if p["normalized_url"] == page["normalized_url"])
    assert again["mentioned_on_page"] == UNREACHABLE and again["mention_detail"] == "timed out"


def _as_real(db, prop):
    """Sample properties are never fetched for; drop the flag and forget one
    cached page so the job has something to do."""
    prop.attributes = {**(prop.attributes or {}), "sample_data": False}
    row = db.query(AICitedPage).filter(AICitedPage.normalized_url.like("zillow.com/%")).first()
    db.delete(row)
    db.commit()


def test_check_job_skips_sample_properties(db, monkeypatch):
    from app.services import content_fetch

    monkeypatch.setattr(content_fetch, "fetch_page_content", lambda url: pytest.fail("sample property fetched"))
    maple = _seeded(db)
    db.delete(db.query(AICitedPage).first())
    db.commit()
    assert check_cited_pages(db, property_id=maple.id, days=28, today=TODAY) == {"fetched": 0, "ok": 0, "pending": 0}


def test_check_job_stores_failed_fetches_and_stops_at_batch(db, monkeypatch):
    from app.services import content_fetch

    def boom(url):
        raise content_fetch.ContentFetchError("HTTP 403: the site refused the request")

    monkeypatch.setattr(content_fetch, "fetch_page_content", boom)
    maple = _seeded(db)
    _as_real(db, maple)
    before = top_citation_pages(db, maple.id, days=28, today=TODAY)
    unchecked = before["check"][UNCHECKED]
    assert unchecked >= 1
    out = check_cited_pages(db, property_id=maple.id, days=28, batch=1, today=TODAY)
    assert out == {"fetched": 1, "ok": 0, "pending": unchecked - 1}
    after = top_citation_pages(db, maple.id, days=28, today=TODAY)
    assert after["check"][UNCHECKED] == unchecked - 1
    assert after["check"][UNREACHABLE] == before["check"][UNREACHABLE] + 1
    blocked = db.query(AICitedPage).filter_by(status="blocked", source="fetch").all()
    assert len(blocked) == 1 and "403" in blocked[0].error


def test_check_job_successful_fetch_is_matched(db, monkeypatch):
    from app.services import content_fetch

    maple = _seeded(db)
    _as_real(db, maple)
    monkeypatch.setattr(content_fetch, "fetch_page_content",
                        lambda url: {"title": "Listing", "body": f"Top picks: {maple.name} and others.", "char_count": 40, "truncated": False})
    check_cited_pages(db, property_id=maple.id, days=28, batch=1, today=TODAY)
    fetched = db.query(AICitedPage).filter_by(source="fetch").one()
    assert fetched.status == "ok"
    page = next(p for p in top_citation_pages(db, maple.id, days=28, today=TODAY)["pages"] if p["normalized_url"] == fetched.normalized_url)
    assert page["mentioned_on_page"] == MENTIONED and maple.name in page["mention_detail"]


def test_sample_removal_drops_sample_page_rows_only(db):
    _seeded(db)
    db.add(AICitedPage(normalized_url="example.org/real", url="https://example.org/real", domain="example.org",
                       fetched_at=NOW, status="ok", body="x", source="fetch"))
    db.commit()
    assert db.query(AICitedPage).filter_by(source="sample").count() > 0
    remove_sample_portfolio(db)
    assert db.query(AICitedPage).filter_by(source="sample").count() == 0
    assert db.query(AICitedPage).filter_by(source="fetch").count() == 1


def test_rank_ties_share_a_rank():
    ranked = _rank([{"name": "A", "mentions": 3}, {"name": "B", "mentions": 3}, {"name": "C", "mentions": 1}, {"name": "D", "mentions": 0}])
    assert [(e["name"], e["rank"]) for e in ranked] == [("A", 1), ("B", 1), ("C", 3)]


def test_topic_rankings_reconcile_with_mentions(db):
    maple = _seeded(db)
    out = topic_rankings(db, maple.id, days=28, today=TODAY)
    assert out["data_label"] == "MEASURED" and out["topics"]
    comp_ids = {c.id for c in db.query(Competitor).filter_by(property_id=maple.id)}
    assert out["tracked_competitors"] == len(comp_ids)
    for t in out["topics"]:
        obs = db.query(AIPropertyObservation).filter_by(property_id=maple.id, cluster_id=t["cluster_id"], eligible=True).all()
        obs = [o for o in obs if o.observed_at.date() >= out_start(out)]
        assert t["answers"] == len(obs)
        assert t["property_mentions"] == sum(1 for o in obs if o.mentioned)
        rids = [o.response_id for o in obs]
        for e in t["ranked"]:
            if e["is_property"]:
                assert e["mentions"] == t["property_mentions"]
            else:
                n = db.query(Mention).filter(Mention.response_id.in_(rids), Mention.entity_type == ENTITY_COMPETITOR,
                                             Mention.entity_id == e["entity_id"]).count()
                assert e["mentions"] == n
        if not t["sufficient"]:
            assert t["property_rank"] is None and not t["needs_work"]
        ranks = [e["rank"] for e in t["ranked"]]
        assert ranks == sorted(ranks)
    assert out["summary"]["leading"] == sum(1 for t in out["topics"] if t["property_rank"] == 1)


def out_start(out):
    from datetime import date
    return date.fromisoformat(out["window"]["start"])


def test_rankings_and_pages_endpoints(client: TestClient, db):
    maple = _seeded(db)
    r = client.get("/api/ai-observatory/rankings", params={"property_id": maple.id, "days": 28, "today": TODAY.isoformat()})
    assert r.status_code == 200 and r.json()["topics"]
    r = client.get("/api/ai-observatory/citations/pages", params={"property_id": maple.id, "days": 28, "today": TODAY.isoformat(), "limit": 5})
    assert r.status_code == 200 and len(r.json()["pages"]) == 5
    r = client.post("/api/ai-observatory/citations/pages/check", params={"property_id": maple.id})
    assert r.status_code == 200 and r.json()["created"] is True
    r = client.post("/api/ai-observatory/citations/pages/check", params={"property_id": maple.id})
    assert r.json()["created"] is False, "same-day check is idempotent"
    assert client.get("/api/ai-observatory/rankings", params={"property_id": 999999}).status_code == 404


def test_rankings_only_count_tracked_competitors(db):
    maple = _seeded(db)
    out = topic_rankings(db, maple.id, days=28, today=TODAY)
    names = {e["name"] for t in out["topics"] for e in t["ranked"]}
    tracked = {c.name for c in db.query(Competitor).filter_by(property_id=maple.id)} | {maple.name}
    assert names <= tracked
