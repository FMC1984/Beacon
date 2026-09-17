"""Property Truth layer v1: provenance plus a cross-source fact grid."""

from datetime import datetime, timedelta

from app.models import AICitation, AICitedPage, AIClaim, Property, PropertyFact
from app.models.ai_intelligence import CLAIM_CONFLICT
from app.services.observatory.demo_seed import build_sample_portfolio
from app.services.observatory.truth import set_provenance, truth_grid

NOW = datetime(2026, 9, 10, 12, 0)
TODAY = NOW.date()


def _seeded(db, name="Maple Ridge Flats"):
    build_sample_portfolio(db, now=NOW, weeks=4)
    return db.query(Property).filter_by(name=name).one()


def _row(grid, key):
    return next(r for r in grid["facts"] if r["fact_key"] == key)


def test_grid_lists_recorded_facts_with_unverified_provenance(db):
    maple = _seeded(db)
    grid = truth_grid(db, maple.id, days=28, today=TODAY)
    keys = {r["fact_key"] for r in grid["facts"]}
    assert {"pets", "rent", "state"} <= keys and any(k.startswith("amenity:") for k in keys)
    assert grid["columns"][0]["key"] == "website" and grid["columns"][-1]["key"] == "ai_answers"
    assert all(r["provenance"]["status"] == "unverified" for r in grid["facts"])
    assert grid["summary"]["unverified"] == len(grid["facts"])
    # Rent is volatile by default and is never graded as a conflict anywhere.
    rent = _row(grid, "rent")
    assert rent["provenance"]["freshness"] == "volatile"
    assert all(c["state"] != "conflicts" for c in rent["cells"].values())


def test_unread_and_blocked_sources_are_never_called_silent(db):
    maple = _seeded(db)
    grid = truth_grid(db, maple.id, days=28, today=TODAY)
    listing = next(c["key"] for c in grid["columns"] if c["kind"] == "listing")
    for page in db.query(AICitedPage).filter(AICitedPage.domain == listing).all():
        page.status, page.error, page.body = "blocked", "HTTP 403", None
    db.commit()
    again = truth_grid(db, maple.id, days=28, today=TODAY)
    assert all(r["cells"][listing]["state"] == "unreachable" for r in again["facts"])
    db.query(AICitedPage).filter(AICitedPage.domain == listing).delete()
    db.commit()
    assert all(r["cells"][listing]["state"] == "unread" for r in truth_grid(db, maple.id, days=28, today=TODAY)["facts"])


def test_listing_conflict_and_cited_source_with_the_same_wrong_value(db):
    stone = _seeded(db, "Stonebrook Commons")  # recorded pet policy: not allowed
    assert (stone.attributes or {}).get("pet_policy") == "not_allowed"
    # An AI answer that wrongly says pets are allowed, citing a listing page that says the same.
    claim = AIClaim(
        property_id=stone.id, claim_type="pets", claim_topic="pets", claim_value="pets allowed",
        claim_text="Stonebrook Commons is pet friendly.", verification_status=CLAIM_CONFLICT,
        verification_method="attributes_pet_policy", evidence="Says 'pets allowed', but the recorded pet policy is 'not_allowed'.",
        known_value="not_allowed", severity="high", claim_hash="t" * 64, first_seen=NOW, last_seen=NOW,
        occurrence_count=3, status="open",
    )
    cite = db.query(AICitation).filter(AICitation.normalized_url.like("%harbor-bend%") | AICitation.normalized_url.like("%lakemont%")).first()
    claim.response_ids = [cite.response_id]
    db.add(claim)
    page = db.query(AICitedPage).filter_by(normalized_url=cite.normalized_url).one()
    page.status, page.body = "ok", "Stonebrook Commons is pet friendly and close to downtown."
    db.commit()

    grid = truth_grid(db, stone.id, days=28, today=TODAY)
    pets = _row(grid, "pets")
    # The sample's own scripted answers already carry this conflict; ours adds 3 more occurrences.
    assert pets["cells"]["ai_answers"]["state"] == "conflicts" and pets["cells"]["ai_answers"]["conflict"] >= 3
    assert pets["cells"][page.domain]["state"] == "conflicts"
    origin = pets["cited_sources_with_same_value"]
    assert origin and origin[0]["domain"] == page.domain and origin[0]["value"] == "pets allowed"
    assert grid["facts"][0]["fact_key"] == "pets", "facts with conflicts sort first"
    assert "not proof of origin" in grid["note"]


def test_a_directory_list_naming_other_communities_is_not_attributed_to_this_one(db):
    """'Featured: Lakemont Senior Residences, Stonebrook Commons' must not make
    Stonebrook look like senior housing."""
    stone = _seeded(db, "Stonebrook Commons")
    grid = truth_grid(db, stone.id, days=28, today=TODAY)
    listing = next(c["key"] for c in grid["columns"] if c["kind"] == "listing")
    for page in db.query(AICitedPage).filter(AICitedPage.domain == listing).all():
        page.status = "ok"
        page.body = "Featured communities: Lakemont Senior Residences, Stonebrook Commons, Maple Ridge Flats."
    db.commit()
    again = truth_grid(db, stone.id, days=28, today=TODAY)
    ptype = _row(again, "property_type")["cells"][listing]
    assert ptype["state"] == "not_stated", ptype
    # A sentence about this property alone is still read.
    for page in db.query(AICitedPage).filter(AICitedPage.domain == listing).all():
        page.body += " Stonebrook Commons is a senior living community."
    db.commit()
    assert _row(truth_grid(db, stone.id, days=28, today=TODAY), "property_type")["cells"][listing]["state"] == "conflicts"


def test_provenance_lifecycle_verified_then_stale(db):
    maple = _seeded(db)
    p = set_provenance(db, maple.id, "pets", source_of_truth="Community manager, lease addendum", verified=True, verified_by="Tina")
    assert p["status"] == "verified" and p["source_of_truth"].startswith("Community manager")
    row = db.query(PropertyFact).filter_by(property_id=maple.id, fact_key="pets").one()
    row.verified_at = row.verified_at - timedelta(days=400)
    db.commit()
    assert _row(truth_grid(db, maple.id, days=28, today=TODAY), "pets")["provenance"]["status"] == "stale"


def test_endpoints_and_validation(client, db):
    maple = _seeded(db)
    assert client.get("/api/ai-observatory/truth", params={"property_id": maple.id}).status_code == 200
    ok = client.put("/api/ai-observatory/truth/facts/amenity:pool", params={"property_id": maple.id},
                    json={"verified": True, "source_of_truth": "Site walk", "freshness": "stable"})
    assert ok.status_code == 200 and ok.json()["status"] == "verified"
    assert client.put("/api/ai-observatory/truth/facts/pets", params={"property_id": maple.id}, json={"freshness": "weekly"}).status_code == 422
    assert client.put("/api/ai-observatory/truth/facts/not_a_fact", params={"property_id": maple.id}, json={"verified": True}).status_code == 404
    assert client.get("/api/ai-observatory/truth", params={"property_id": 999999}).status_code == 404


def test_housing_authority_is_not_graded_on_a_single_policy(db):
    p = Property(name="County Housing", slug="county-housing", property_type="housing_authority", state="CO",
                 attributes={"pet_policy": "allowed", "rent_range": {"min": 900, "max": 1200}, "amenities": ["Clubhouse"]})
    db.add(p)
    db.commit()
    grid = truth_grid(db, p.id, today=TODAY)
    keys = {r["fact_key"] for r in grid["facts"]}
    assert "pets" not in keys and "rent" not in keys and "amenity:clubhouse" in keys
    assert any("per development" in n for n in grid["notes"])
