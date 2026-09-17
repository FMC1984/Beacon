"""Cross-property benchmarks (flow P3)."""

from datetime import datetime

from app.models import Property
from app.models.property_profile import PropertyProfile
from app.services.observatory.benchmark import MIN_POOL, property_benchmark
from app.services.observatory.demo_seed import build_sample_portfolio
from app.services.observatory.rollups import rebuild_rollups

NOW = datetime(2026, 9, 10, 12, 0)
TODAY = NOW.date()


def _seeded(db):
    build_sample_portfolio(db, now=NOW, weeks=4)
    rebuild_rollups(db)
    return db.query(Property).filter_by(name="Maple Ridge Flats").one()


def test_sample_property_is_benchmarked_against_sample_peers_only(db):
    maple = _seeded(db)
    real = Property(name="Real Court", slug="real-court", city="Denver", state="CO")
    db.add(real)
    db.commit()
    out = property_benchmark(db, maple.id, days=28, today=TODAY)
    assert out["is_sample"] is True
    pool = out["all"]["pool"]
    assert pool["properties"] >= MIN_POOL and pool["properties"] <= 7, "the seven other sample properties at most"
    row = out["all"]["metrics"]["ai_visibility"]
    assert row["benchmark_value"] is not None and row["data_label"] == "MEASURED"
    assert row["property_value"] is not None and row["point_change"] is not None
    # The real property sees no pool at all: nothing real to compare with.
    r = property_benchmark(db, real.id, days=28, today=TODAY)
    assert r["all"]["pool"]["properties"] == 0
    assert r["all"]["metrics"]["ai_visibility"]["data_label"] == "UNAVAILABLE"


def test_pool_below_minimum_is_unavailable_with_a_reason(db):
    maple = _seeded(db)
    # Deactivate all but two other sample properties.
    others = db.query(Property).filter(Property.id != maple.id).order_by(Property.id).all()
    for p in others[2:]:
        p.is_active = False
    db.commit()
    out = property_benchmark(db, maple.id, days=28, today=TODAY)
    row = out["all"]["metrics"]["ai_visibility"]
    assert row["benchmark_value"] is None and row["data_label"] == "UNAVAILABLE"
    assert "at least 3" in row["note"]


def test_segment_pool_needs_a_property_type(db):
    maple = _seeded(db)
    out = property_benchmark(db, maple.id, days=28, today=TODAY)
    seg = out["segment_pool"]["metrics"]["ai_visibility"]
    if out["segment"] is None:
        assert seg["data_label"] == "UNAVAILABLE" and "Property Context" in seg["note"]
    else:
        assert seg["properties"] <= out["all"]["pool"]["properties"]
    db.query(PropertyProfile).filter_by(property_id=maple.id).delete()
    db.commit()
    out = property_benchmark(db, maple.id, days=28, today=TODAY)
    assert out["segment"] is None


def test_benchmark_endpoint(client, db):
    maple = _seeded(db)
    r = client.get("/api/ai-observatory/benchmark", params={"property_id": maple.id, "days": 28, "today": TODAY.isoformat()})
    assert r.status_code == 200 and r.json()["minimum_pool"] == MIN_POOL
    assert client.get("/api/ai-observatory/benchmark", params={"property_id": 999999}).status_code == 404
