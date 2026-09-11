"""Phase 19 (2): prompt generation. Market/feature prompts are created once
per market and shared; brand prompts per property; every generated prompt
carries provenance; generation is idempotent by text hash; market prompts
never contain property-private data; competitor comparisons come only from
tracked competitors."""

from app.models import AIVisibilityPrompt, Competitor, Market, Property, PropertyContent
from app.services.observatory.markets import assign_property_market
from app.services.observatory.prompt_library import (
    generate_market_prompts,
    generate_property_prompts,
    prompt_hash,
    property_signal_topics,
)
from app.services.observatory.taxonomy import core_topic_keys, topics_in_text


def _prop(db, name="Gen Court", city="Castle Rock", state="CO", **kw):
    p = Property(name=name, slug=name.lower().replace(" ", "-"), city=city, state=state, **kw)
    db.add(p)
    db.commit()
    assign_property_market(db, p)
    db.commit()
    return p


def test_taxonomy_matching_and_core_topics():
    assert "pets" in topics_in_text("We are pet friendly with a dog park")
    assert "dog_park" in topics_in_text("We are pet friendly with a dog park")
    assert "ev_charging" in topics_in_text("EV charging stations in the garage")
    assert "rent" in core_topic_keys() and "pets" in core_topic_keys()


def test_market_prompts_are_shared_and_idempotent(db):
    p = _prop(db)
    out = generate_market_prompts(db, p.market_id)
    assert out["prompts_created"] == out["prompts_total"] > 20
    market_rows = db.query(AIVisibilityPrompt).filter_by(market_id=p.market_id, property_id=None).all()
    assert all(r.property_id is None for r in market_rows)
    assert {r.scope for r in market_rows} == {"market", "feature"}
    assert all(r.generated_from["template_id"] for r in market_rows)
    assert all(r.generation_method == "template" for r in market_rows)
    assert all(r.prompt_hash == prompt_hash(r.prompt_text) for r in market_rows)
    # No property-private data in shared prompts.
    assert not any("Gen Court" in r.prompt_text for r in market_rows)
    assert any("Castle Rock, CO" in r.prompt_text for r in market_rows)
    # Variants exist but only one representative per template group.
    groups = {}
    for r in market_rows:
        groups.setdefault(r.variant_group, []).append(r)
    assert any(len(v) > 1 for v in groups.values())
    assert all(sum(1 for r in v if r.is_representative) == 1 for v in groups.values())

    again = generate_market_prompts(db, p.market_id)
    assert again["prompts_created"] == 0 and again["prompts_total"] == out["prompts_total"]


def test_property_prompts_include_brand_and_competitor_comparisons(db):
    p = _prop(db, "Brand Court")
    db.add(Competitor(property_id=p.id, name="Rival Ridge"))
    db.commit()
    out = generate_property_prompts(db, p.id)
    brand = db.query(AIVisibilityPrompt).filter_by(property_id=p.id, scope="brand").all()
    assert out["brand_prompts_created"] == len(brand) >= 6
    assert any("Brand Court vs Rival Ridge" in r.prompt_text for r in brand)
    assert all("Brand Court" in r.prompt_text or "Castle Rock" in r.prompt_text for r in brand)
    assert all(r.cadence == "monthly" for r in brand)
    assert out["market_prompts_total"] > 0  # the shared universe came along
    assert "pets" in out["signal_topics"] and "core" in out["signal_topics"]["pets"]


def test_housing_authority_uses_its_own_brand_templates(db):
    p = _prop(db, "Douglas Housing", property_type="housing_authority")
    generate_property_prompts(db, p.id)
    texts = [r.prompt_text for r in db.query(AIVisibilityPrompt).filter_by(property_id=p.id).all()]
    assert any("housing assistance with Douglas Housing" in t for t in texts)
    assert not any("pet friendly" in t.lower() for t in texts)


def test_signal_topics_come_from_attributes_content_and_never_guess(db):
    p = _prop(db, "Signal Court", attributes={"amenities": ["EV charging", "dog park"], "segment": "luxury"})
    db.add(PropertyContent(property_id=p.id, page="amenities", title="A",
                           body="Resort pool and covered parking.", topics=["amenities", "parking"]))
    db.commit()
    signals = property_signal_topics(db, p)
    assert "attributes" in signals["ev_charging"]
    assert "attributes" in signals["dog_park"]
    assert "attributes" in signals["luxury"]
    assert "content" in signals["pool"] and "content" in signals["parking"]
    assert "student" not in signals  # nothing said student; not invented


def test_half_filled_templates_are_never_emitted(db):
    p = Property(name="No City Court", slug="no-city-court")
    db.add(p)
    db.commit()
    out = generate_property_prompts(db, p.id)
    texts = [r.prompt_text for r in out["prompts"]]
    assert texts and all("{" not in t for t in texts)
    assert out["market_id"] is None and out["market_prompts_total"] == 0
