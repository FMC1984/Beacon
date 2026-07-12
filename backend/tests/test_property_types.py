"""Property client/site type: default, validation, config endpoint, and its
effect on Content Intelligence (which knowledge base drives scoring) and Nora
context. Distinct from PropertyProfile.property_type (regulatory type)."""

from datetime import datetime, timezone

from app.models import Property, PropertyContent
from app.services.content_intelligence import (
    analyze_property,
    content_intelligence_summary_text,
)


def _content(db, pid, page, body):
    db.add(PropertyContent(
        property_id=pid, page=page, title=page.title(), body=body,
        updated_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
    ))
    db.commit()


# --- default + validation ---


def test_new_property_defaults_to_multifamily(client):
    p = client.post("/api/properties", json={"name": "Default Prop"}).json()
    assert p["property_type"] == "multifamily_apartment"


def test_existing_rows_default_via_migration(db):
    # Rows created without specifying property_type get the server_default.
    p = Property(name="Legacy Prop", slug="legacy-prop")
    db.add(p)
    db.commit()
    db.refresh(p)
    assert p.property_type == "multifamily_apartment"


def test_create_housing_authority(client):
    p = client.post(
        "/api/properties",
        json={"name": "DCHP Agency", "property_type": "housing_authority"},
    ).json()
    assert p["property_type"] == "housing_authority"


def test_invalid_property_type_rejected(client):
    r = client.post(
        "/api/properties", json={"name": "Bad Type", "property_type": "spaceship"}
    )
    assert r.status_code == 422
    assert "Unknown property_type" in r.json()["detail"]


def test_update_property_type(client):
    pid = client.post("/api/properties", json={"name": "Switch Prop"}).json()["id"]
    r = client.patch(f"/api/properties/{pid}", json={"property_type": "housing_authority"})
    assert r.status_code == 200
    assert r.json()["property_type"] == "housing_authority"
    # invalid update rejected
    assert client.patch(f"/api/properties/{pid}", json={"property_type": "nope"}).status_code == 422


def test_types_config_endpoint(client):
    cfg = client.get("/api/properties/types/config").json()
    assert cfg["default"] == "multifamily_apartment"
    assert set(cfg["types"]) == {"multifamily_apartment", "housing_authority"}
    ha = cfg["types"]["housing_authority"]
    assert ha["terminology"]["unit_plural"] == "developments"
    assert "crm" not in ha["allowed_connectors"]  # HA has fewer connectors


# --- uploads are gated by the type's allowed_connectors ---


def test_housing_authority_rejects_unsupported_upload(client):
    pid = client.post(
        "/api/properties",
        json={"name": "HA Uploads", "property_type": "housing_authority"},
    ).json()["id"]
    # A housing authority has no CRM connector.
    r = client.post(
        "/api/uploads/crm",
        data={"property_id": str(pid)},
        files={"file": ("leads.csv", b"a,b\n1,2\n", "text/csv")},
    )
    assert r.status_code == 422
    assert "does not support" in r.json()["detail"]


def test_multifamily_allows_supported_upload_past_the_gate(client):
    pid = client.post("/api/properties", json={"name": "MF Uploads"}).json()["id"]
    # Multifamily supports CRM; a bad file fails on parsing (422), not the gate.
    r = client.post(
        "/api/uploads/crm",
        data={"property_id": str(pid)},
        files={"file": ("leads.csv", b"not a real crm file\n", "text/csv")},
    )
    assert "does not support" not in (r.json().get("detail") or "")


# --- Content Intelligence is type-driven ---


def test_housing_authority_uses_applicant_questions(db):
    p = Property(name="HA CI", slug="ha-ci", property_type="housing_authority")
    db.add(p)
    db.commit()
    _content(db, p.id, "homepage", "Apply for Section 8 and check eligibility. Join the waitlist.")
    a = analyze_property(db, p.id)
    assert a["property_type"] == "housing_authority"
    questions = {q["question"] for q in a["question_coverage"]["questions"]}
    assert "How do I apply for housing assistance?" in questions
    assert "What is the pet policy?" not in questions  # apartment question absent


def test_multifamily_uses_renter_questions(db):
    p = Property(name="MF CI", slug="mf-ci")  # defaults multifamily
    db.add(p)
    db.commit()
    _content(db, p.id, "homepage", "Welcome to our apartments in Tempe.")
    a = analyze_property(db, p.id)
    assert a["property_type"] == "multifamily_apartment"
    questions = {q["question"] for q in a["question_coverage"]["questions"]}
    assert "What is the pet policy?" in questions
    assert "How do I apply for housing assistance?" not in questions


def test_housing_authority_content_intent_topics(db):
    p = Property(name="HA Intent", slug="ha-intent", property_type="housing_authority")
    db.add(p)
    db.commit()
    _content(db, p.id, "amenities", "We administer the Housing Choice Voucher and public housing programs.")
    a = analyze_property(db, p.id)
    amenities = next(r for r in a["keyword_intent"] if r["page"] == "amenities")
    # HA amenities page expects program topics, not apartment amenities.
    labels = amenities["covered_topics"] + amenities["missing_topics"]
    assert any("Voucher" in label or "Public housing" in label for label in labels)


# --- Nora context carries the site type ---


def test_ci_summary_mentions_site_type(db):
    p = Property(name="HA Summary", slug="ha-summary", property_type="housing_authority")
    db.add(p)
    db.commit()
    _content(db, p.id, "homepage", "Apply for housing assistance and check eligibility.")
    text = content_intelligence_summary_text(analyze_property(db, p.id))
    assert "Housing authority" in text


def test_property_context_chunk_mentions_site_type(db):
    from app.services.property_context import get_property_context, property_context_chunk_text
    from app.models import PropertyProfile

    p = Property(name="HA Ctx", slug="ha-ctx", property_type="housing_authority")
    db.add(p)
    db.commit()
    db.add(PropertyProfile(property_id=p.id, property_type="affordable"))
    db.commit()
    ctx = get_property_context(db, p.id)
    assert ctx["site_type"] == "housing_authority"
    assert "Housing authority" in property_context_chunk_text(ctx)
