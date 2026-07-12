"""The deterministic Content Intelligence analyzer: keyword intent, question
coverage, neighborhood, freshness, opportunities, scoring, determinism."""

from datetime import date, datetime, timezone

from app.models import Property, PropertyContent
from app.services.content_intelligence import analyze_property
from tests.test_phase2_uploads import make_property

TODAY = date(2026, 7, 5)

RICH_HOMEPAGE = (
    "Solara Flats is located in the heart of Tempe, minutes from ASU and Loop 101. "
    "Resort-style pool with a spa, a 24-hour fitness center with cardio and weights, "
    "and a clubhouse. Studio, one bedroom, and two bedroom floor plans with granite "
    "counters and in-unit washer and dryer, starting at $1,450 per month. Pet-friendly "
    "with a dog park; breed restrictions apply and a pet fee is required. Assigned "
    "covered parking and EV charging with level 2 stations. Schedule a tour with our "
    "leasing office, open Monday through Saturday."
)
RICH_NEIGHBORHOOD = (
    "Steps from Tempe Marketplace shopping and dozens of restaurants and coffee shops. "
    "Highly rated schools in the district and close to ASU. Major employers downtown and "
    "at the nearby tech corridor and hospital. Papago Park trails and a lake for "
    "recreation, plus light rail transit and easy freeway commute. Banner medical center "
    "and the theater district are minutes away."
)


def seed_content(db, property_id, page, body, keyword=None, updated=None):
    db.add(
        PropertyContent(
            property_id=property_id,
            page=page,
            title=page.title(),
            body=body,
            mapped_keyword=keyword,
            updated_at=updated or datetime(2026, 6, 15, tzinfo=timezone.utc),
        )
    )
    db.commit()


def make_prop_row(db, name="Analysis Property"):
    prop = Property(name=name, slug=name.lower().replace(" ", "-"))
    db.add(prop)
    db.commit()
    return prop


# --- no content ---


def test_no_content_is_honest(db):
    prop = make_prop_row(db)
    a = analyze_property(db, prop.id, today=TODAY)
    assert a["has_content"] is False
    assert a["score"] is None
    assert a["opportunities"][0]["title"] == "Add website content"


# --- determinism ---


def test_analysis_is_deterministic(db):
    prop = make_prop_row(db)
    seed_content(db, prop.id, "homepage", RICH_HOMEPAGE, "apartments in tempe az")
    a1 = analyze_property(db, prop.id, today=TODAY)
    a2 = analyze_property(db, prop.id, today=TODAY)
    assert a1 == a2


# --- keyword intent (topic coverage, not frequency) ---


def test_keyword_intent_satisfied_and_missing(db):
    prop = make_prop_row(db)
    seed_content(db, prop.id, "homepage", RICH_HOMEPAGE, "apartments in tempe az")
    seed_content(db, prop.id, "faq", "We are pet friendly.", "faq tempe")
    a = analyze_property(db, prop.id, today=TODAY)
    intents = {r["page"]: r for r in a["keyword_intent"]}
    assert intents["homepage"]["intent_satisfied"] is True
    assert intents["homepage"]["topic_complete"] is True
    # Sparse FAQ page fails intent and lists missing topics.
    assert intents["faq"]["intent_satisfied"] is False
    assert intents["faq"]["missing_topics"]
    assert "frequency" in intents["homepage"]["explanation"]


# --- question coverage ---


def test_question_statuses(db):
    prop = make_prop_row(db)
    # pool has concept+detail (answered); "lease" concept only (partial); no pet (missing).
    seed_content(
        db, prop.id, "amenities",
        "Resort-style pool with a spa. Ask the office about a lease today.",
    )
    a = analyze_property(db, prop.id, today=TODAY)
    q = {x["id"]: x for x in a["question_coverage"]["questions"]}
    assert q["pool"]["status"] == "answered"
    assert q["pool"]["citations"]
    assert q["lease_terms"]["status"] == "partial"
    assert q["pet_policy"]["status"] == "missing"
    assert q["pet_policy"]["citations"] == []
    s = a["question_coverage"]["summary"]
    assert s["answered"] + s["partial"] + s["missing"] == s["total"]


# --- neighborhood ---


def test_neighborhood_rating(db):
    prop = make_prop_row(db)
    seed_content(db, prop.id, "neighborhood", RICH_NEIGHBORHOOD, "tempe neighborhood")
    a = analyze_property(db, prop.id, today=TODAY)
    nb = a["neighborhood"]
    assert nb["rating"] in ("Good", "Excellent")
    assert nb["citations"]
    assert "of 9 neighborhood topics" in nb["explanation"]


def test_neighborhood_poor_when_sparse(db):
    prop = make_prop_row(db)
    seed_content(db, prop.id, "homepage", "A pool and a gym. Nice apartments.")
    a = analyze_property(db, prop.id, today=TODAY)
    assert a["neighborhood"]["rating"] == "Poor"


# --- freshness ---


def test_freshness_detects_outdated_promo(db):
    prop = make_prop_row(db)
    seed_content(
        db, prop.id, "homepage",
        "Spring special: one month free if you move in by March 2024!",
        updated=datetime(2024, 3, 1, tzinfo=timezone.utc),
    )
    a = analyze_property(db, prop.id, today=TODAY)
    assert a["freshness"]["status"] == "stale"
    issues = {f["issue"] for f in a["freshness"]["findings"]}
    assert "outdated promotion" in issues


def test_freshness_unknown_says_so(db):
    prop = make_prop_row(db)
    # No dates in body, no updated_at.
    db.add(
        PropertyContent(
            property_id=prop.id, page="homepage", title="Home",
            body="A lovely community with a pool.", updated_at=None,
        )
    )
    db.commit()
    a = analyze_property(db, prop.id, today=TODAY)
    assert a["freshness"]["determinable"] is False
    assert "cannot be determined" in a["freshness"]["explanation"]


# --- opportunities ---


def test_opportunities_prioritized_and_grounded(db):
    prop = make_prop_row(db)
    seed_content(db, prop.id, "homepage", "A pool and a gym.")
    a = analyze_property(db, prop.id, today=TODAY)
    ops = a["opportunities"]
    assert ops
    # High impact + Low effort should sort ahead of Medium/Medium.
    ranks = [(o["impact"], o["effort"]) for o in ops]
    assert ranks[0][0] == "High"
    for o in ops:
        assert o["title"] and o["reason"]
        assert o["impact"] in ("High", "Medium", "Low")
        assert o["effort"] in ("High", "Medium", "Low")
        assert "priority" in o


# --- scoring (explainable, never black-box) ---


def test_score_is_explainable(db):
    prop = make_prop_row(db)
    seed_content(db, prop.id, "homepage", RICH_HOMEPAGE, "apartments in tempe az")
    seed_content(db, prop.id, "neighborhood", RICH_NEIGHBORHOOD)
    a = analyze_property(db, prop.id, today=TODAY)
    score = a["score"]
    assert 0 <= score["value"] <= 100
    assert score["grade"] in ("Poor", "Basic", "Good", "Excellent")
    components = {b["component"] for b in score["breakdown"]}
    assert {"keyword_intent", "question_coverage", "neighborhood"} <= components
    assert all(b["explanation"] for b in score["breakdown"])
    assert abs(sum(b["weight"] for b in score["breakdown"]) - 1.0) < 0.01


def test_freshness_excluded_from_score_when_indeterminable(db):
    prop = make_prop_row(db)
    db.add(
        PropertyContent(
            property_id=prop.id, page="homepage", title="Home",
            body="A pool and a gym.", updated_at=None,
        )
    )
    db.commit()
    a = analyze_property(db, prop.id, today=TODAY)
    components = {b["component"] for b in a["score"]["breakdown"]}
    assert "freshness" not in components
