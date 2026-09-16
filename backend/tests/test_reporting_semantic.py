"""Semantic Intelligence report: topic coverage across site content, reviews,
AI answers and search, and the gaps between them. The report must never turn
a source the property does not have into a finding about the property."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import (
    AIPropertyObservation,
    AIVisibilityQuery,
    GSCPerformanceDaily,
    Property,
    PropertyContent,
    PropertyReview,
    SourceType,
    Upload,
    UploadStatus,
)
from app.services.reporting_semantic import (
    MIN_IMPRESSIONS_FOR_DEMAND,
    MIN_REVIEWS_FOR_SENTIMENT,
    build_semantic_report,
)

NOW = datetime.now(timezone.utc).replace(tzinfo=None)
TODAY = NOW.date()


def _prop(db, name="Semantic Court"):
    p = Property(name=name, slug=name.lower().replace(" ", "-"), city="Parker", state="CO")
    db.add(p)
    db.commit()
    return p


def _page(db, prop, page, body):
    db.add(PropertyContent(property_id=prop.id, page=page, title=page.title(), body=body))
    db.commit()


def _review(db, prop, body, rating=4.0):
    db.add(PropertyReview(property_id=prop.id, provider="google", body=body, rating=rating,
                          review_date=TODAY - timedelta(days=5)))
    db.commit()


def _answer(db, prop, text):
    q = AIVisibilityQuery(property_id=prop.id, platform="chatgpt", prompt_text="q",
                          raw_response_text=text, executed_at=NOW, execution_status="success")
    db.add(q)
    db.flush()
    db.add(AIPropertyObservation(property_id=prop.id, response_id=q.id, platform="chatgpt",
                                 observed_at=NOW, eligible=True, mentioned=True))
    db.commit()


def _search(db, prop, query, impressions):
    up = db.query(Upload).filter_by(property_id=prop.id, source_type=SourceType.GSC).first()
    if up is None:
        up = Upload(source_type=SourceType.GSC, property_id=prop.id, filename="s.csv",
                    status=UploadStatus.PROCESSED)
        db.add(up)
        db.flush()
    db.add(GSCPerformanceDaily(property_id=prop.id, upload_id=up.id, date=TODAY - timedelta(days=2),
                               query=query, clicks=1, impressions=impressions, ctr=0.01, position=9.0))
    db.commit()


def _topic(report, key):
    return next(t for t in report["topics"] if t["key"] == key)


def test_scope_and_missing_property(db):
    assert build_semantic_report(db, None)["scope_required"] is True
    with pytest.raises(ValueError):
        build_semantic_report(db, 9999)


def test_topic_covered_when_several_sources_agree(db):
    p = _prop(db)
    _page(db, p, "amenities", "Our pool and fitness center are open daily.")
    _review(db, p, "The pool is clean and the fitness center is great.")
    _review(db, p, "We use the pool every weekend.")
    _answer(db, p, "Semantic Court has a pool and a fitness center.")
    r = build_semantic_report(db, p.id, today=TODAY)

    amenities = _topic(r, "amenities")
    assert amenities["coverage_state"] == "covered"
    assert set(amenities["signal_sources"]) == {"content", "reviews", "ai_answers"}
    assert amenities["content"]["pages"] == ["amenities"]
    assert amenities["reviews"]["mentions"] == 2
    assert amenities["reviews"]["lean"] == "positive"
    assert r["summary"]["sources_available"] == 3  # no Search Console
    assert r["taxonomy_version"]


def test_a_missing_source_is_named_not_treated_as_a_gap(db):
    """The honesty case: a property with no reviews and no Search Console must
    not produce 'residents talk about X' or 'people search for X' findings."""
    p = _prop(db)
    _page(db, p, "homepage", "A quiet community with covered parking.")
    r = build_semantic_report(db, p.id, today=TODAY)

    states = {s["key"]: s["state"] for s in r["sources"]}
    assert states["reviews"] == "not_configured" and states["search"] == "not_configured"
    assert states["ai_answers"] == "awaiting_data"
    assert not any(g["type"] in ("content_gap", "demand_gap", "ai_gap") for g in r["gaps"])
    assert _topic(r, "parking")["coverage_state"] == "site_only"
    # A topic nobody raised is "not discussed", not a gap.
    assert _topic(r, "pest")["coverage_state"] == "not_discussed"


def test_content_gap_when_residents_raise_a_topic_the_site_ignores(db):
    p = _prop(db)
    _page(db, p, "homepage", "Welcome to Semantic Court.")
    _review(db, p, "Maintenance never fixed my broken heater.", rating=2.0)
    _review(db, p, "Repairs take weeks and the work order was ignored.", rating=1.0)
    r = build_semantic_report(db, p.id, today=TODAY)

    gap = next(g for g in r["gaps"] if g["topic"] == "maintenance")
    assert gap["type"] == "content_gap"
    assert "Residents talk about maintenance" in gap["headline"]
    assert any("2 review(s)" in e for e in gap["evidence"])
    # The topic is clearly raised, but the lexicon recognizes none of these
    # words as sentiment, so no lean is claimed rather than one invented.
    reviews = _topic(r, "maintenance")["reviews"]
    assert reviews["mentions"] == 2 and reviews["sentiment_detected"] is False
    assert reviews["lean"] is None

    _review(db, p, "The maintenance team is terrible and rude.", rating=1.0)
    _review(db, p, "Awful repair service, totally unresponsive.", rating=1.0)
    graded = _topic(build_semantic_report(db, p.id, today=TODAY), "maintenance")["reviews"]
    assert graded["sentiment_detected"] is True and graded["lean"] == "negative"


def test_demand_gap_needs_real_search_volume(db):
    p = _prop(db)
    _page(db, p, "homepage", "Welcome to Semantic Court.")
    _search(db, p, "semantic court pet friendly", MIN_IMPRESSIONS_FOR_DEMAND - 1)
    thin = build_semantic_report(db, p.id, today=TODAY)
    pets = _topic(thin, "pets")
    assert pets["search"]["present"] and pets["search"]["is_demand"] is False
    assert not any(g["type"] == "demand_gap" for g in thin["gaps"])

    _search(db, p, "pet friendly apartments parker", MIN_IMPRESSIONS_FOR_DEMAND)
    loud = build_semantic_report(db, p.id, today=TODAY)
    gap = next(g for g in loud["gaps"] if g["topic"] == "pets")
    assert gap["type"] == "demand_gap"
    assert _topic(loud, "pets")["search"]["is_demand"] is True


def test_a_generic_query_containing_a_topic_word_is_not_a_demand_gap(db):
    """"apartments for rent" contains the pricing term "rent" but is a generic
    discovery search. Counting it is fine; claiming the site has a pricing gap
    because of it would be an invented finding."""
    p = _prop(db)
    _page(db, p, "homepage", "Welcome to Semantic Court.")
    _search(db, p, "semantic court apartments for rent", MIN_IMPRESSIONS_FOR_DEMAND * 8)
    generic = build_semantic_report(db, p.id, today=TODAY)
    pricing = _topic(generic, "pricing")
    assert pricing["search"]["present"] is True  # observed, and shown
    assert pricing["search"]["specific_impressions"] == 0
    assert pricing["search"]["is_demand"] is False
    assert not any(g["topic"] == "pricing" for g in generic["gaps"])

    # A query actually about pricing does raise it.
    _search(db, p, "semantic court rent increase", MIN_IMPRESSIONS_FOR_DEMAND)
    real = build_semantic_report(db, p.id, today=TODAY)
    gap = next(g for g in real["gaps"] if g["topic"] == "pricing")
    assert gap["type"] == "demand_gap"
    assert "rent increase" in gap["evidence"][0]
    # Evidence quotes the specific impressions, not the generic ones.
    assert str(MIN_IMPRESSIONS_FOR_DEMAND) in gap["evidence"][0]


def test_whole_word_matching_keeps_coffee_out_of_fees(db):
    p = _prop(db)
    _page(db, p, "homepage", "Welcome.")
    _search(db, p, "coffee shop near semantic court", MIN_IMPRESSIONS_FOR_DEMAND * 4)
    r = build_semantic_report(db, p.id, today=TODAY)
    assert _topic(r, "pricing")["search"]["present"] is False


def test_mismatch_when_the_site_markets_what_reviews_dislike(db):
    p = _prop(db)
    _page(db, p, "amenities", "Reserved covered parking for every resident.")
    _review(db, p, "Parking is terrible and the garage is always full.", rating=2.0)
    _review(db, p, "Awful parking situation every night.", rating=1.0)
    r = build_semantic_report(db, p.id, today=TODAY)

    gap = next(g for g in r["gaps"] if g["topic"] == "parking")
    assert gap["type"] == "mismatch"
    assert "reviews lean negative" in gap["headline"]
    assert any("amenities" in e for e in gap["evidence"])


def test_sentiment_needs_a_minimum_sample_and_negation_is_respected(db):
    p = _prop(db)
    _review(db, p, "The pool was lovely.")
    single = _topic(build_semantic_report(db, p.id, today=TODAY), "amenities")
    assert single["reviews"]["mentions"] == 1
    assert single["reviews"]["state"] == "insufficient_sample"
    assert single["reviews"]["lean"] is None  # never characterized from one review
    assert single["reviews"]["minimum_sample"] == MIN_REVIEWS_FOR_SENTIMENT

    q = _prop(db, "Negation Court")
    _review(db, q, "We did not have a maintenance issue the whole year.")
    assert _topic(build_semantic_report(db, q.id, today=TODAY), "maintenance")["reviews"]["present"] is False


def test_clustering_stays_deferred_and_limitations_are_stated(db):
    p = _prop(db)
    _page(db, p, "homepage", "Welcome.")
    r = build_semantic_report(db, p.id, today=TODAY)
    assert any("15c" in d for d in r["deferred"])
    assert any("not a language model" in lim for lim in r["limitations"])
    assert "—" not in str(r)


def test_endpoint_serves_the_report(db, client):
    p = _prop(db)
    _page(db, p, "amenities", "Our pool is open daily.")
    body = client.get(f"/api/reports/semantic?property_id={p.id}").json()
    assert body["property_name"] == "Semantic Court"
    assert body["summary"]["topics_total"] == 17
    assert client.get("/api/reports/semantic?property_id=9999").status_code == 404
    assert client.get("/api/reports/semantic").json()["scope_required"] is True

    meta = client.get("/api/reports/meta").json()
    semantic = next(t for t in meta["tabs"] if t["key"] == "semantic")
    assert semantic["status"] == "available"
