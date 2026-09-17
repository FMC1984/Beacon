"""Property setup checklist (P1 flow work)."""

from datetime import date, datetime

from app.models import Competitor, GA4SessionsDaily, Property, PropertyProfile, SourceType, Upload, UploadStatus
from app.services.observatory.demo_seed import build_sample_portfolio
from app.services.setup import property_setup

STEP_KEYS = ["identity", "data", "facts", "competitors", "prompts", "monitoring"]


def test_bare_property_has_every_step_open_and_names_the_next(client):
    p = client.post("/api/properties", json={"name": "Bare Prop"}).json()
    r = client.get(f"/api/properties/{p['id']}/setup")
    assert r.status_code == 200
    out = r.json()
    assert [s["key"] for s in out["steps"]] == STEP_KEYS
    assert out["done"] == 0 and out["percent"] == 0 and out["complete"] is False
    assert out["next"]["key"] == "identity"
    ident = out["steps"][0]
    assert any("city and state" in m for m in ident["missing"])
    assert any("website" in m for m in ident["missing"])
    assert all(s["href"] and s["unlocks"] for s in out["steps"])


def test_steps_flip_as_rows_appear(db):
    prop = Property(name="Step Prop", slug="step-prop", city="Denver", state="CO", website_url="https://stepprop.com")
    db.add(prop)
    db.commit()
    out = property_setup(db, prop.id)
    assert out["steps"][0]["done"] is True and out["next"]["key"] == "data"

    upload = Upload(source_type=SourceType.GA4, property_id=prop.id, filename="ga4.csv", status=UploadStatus.PROCESSED)
    db.add(upload)
    db.flush()
    db.add(GA4SessionsDaily(property_id=prop.id, date=date(2026, 9, 1), session_source="google", session_medium="organic",
                            sessions=5, upload_id=upload.id))
    db.add(PropertyProfile(property_id=prop.id, property_type="conventional"))
    db.add(Competitor(property_id=prop.id, name="Rival Flats"))
    db.commit()
    out = property_setup(db, prop.id)
    by = {s["key"]: s for s in out["steps"]}
    assert by["data"]["done"] and "GA4" in by["data"]["detail"]
    assert any("Search Console" in m for m in by["data"]["missing"]), "GSC still missing is reported, not hidden"
    assert by["facts"]["done"] and by["competitors"]["done"]
    assert out["next"]["key"] == "prompts" and out["done"] == 4 and out["percent"] == 67


def test_housing_authority_never_asks_for_a_single_policy(db):
    prop = Property(name="HA Prop", slug="ha-prop", property_type="housing_authority", city="Castle Rock", state="CO",
                    website_url="https://ha.example")
    db.add(prop)
    db.commit()
    facts = next(s for s in property_setup(db, prop.id)["steps"] if s["key"] == "facts")
    assert not any("pets" in h for h in facts["optional_hints"])
    assert any("per development" in h for h in facts["optional_hints"])


def test_sample_property_is_complete_and_flagged(db):
    build_sample_portfolio(db, now=datetime(2026, 9, 10, 12, 0), weeks=4)
    maple = db.query(Property).filter_by(name="Maple Ridge Flats").one()
    out = property_setup(db, maple.id)
    assert out["complete"] is True and out["next"] is None and out["is_sample"] is True


def test_unknown_property_is_404(client):
    assert client.get("/api/properties/999999/setup").status_code == 404
