"""Phase 18C: topic-aware Share of Voice opportunity buckets, extending the
existing "competitors" Opportunity Engine source (no new source key, avoids
double corroboration). Never reads prompt-volume or demand data Beacon does
not reliably have - only the operator-asserted AITopic.priority field."""

from datetime import datetime, timedelta, timezone

from app.connectors.base import AIVisibilityQueryProvider
from app.models import AITopic, AIVisibilityPrompt, Competitor, Property
from app.services.ai_visibility import run_query
from app.services.competitor_intelligence.analyzer import _topic_recommendations
from app.services.opportunity_engine import build_opportunities


class FR(AIVisibilityQueryProvider):
    def __init__(self, response):
        self.response = response

    def execute_query(self, prompt, platform):
        return self.response

    def get_queries(self, db, property_id):
        return []


def _prop(db, name="Opp SoV Court"):
    p = Property(name=name, slug=name.lower().replace(" ", "-"))
    db.add(p)
    db.commit()
    return p


TODAY = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def test_protect_bucket_for_high_priority_topic_leader(db):
    p = _prop(db)
    comp = Competitor(property_id=p.id, name="Rival Co")
    db.add(comp)
    db.commit()
    topic = AITopic(property_id=p.id, topic_name="Amenities", priority="high")
    db.add(topic)
    db.commit()
    prompt = AIVisibilityPrompt(
        property_id=p.id, prompt_text="What amenities?", platform="chatgpt",
        topic_id=topic.id,
    )
    db.add(prompt)
    db.commit()

    for _ in range(3):
        run_query(
            db, p.id, "What amenities?", "chatgpt",
            provider=FR("Opp SoV Court has a great pool."), now=TODAY,
        )

    recs = _topic_recommendations(db, p.id, TODAY.date())
    assert any("Protect" in r["title"] for r in recs)
    protect = next(r for r in recs if "Protect" in r["title"])
    assert protect["state"] == "Monitor"


def test_high_priority_bucket_for_declining_large_gap(db):
    p = _prop(db)
    comp = Competitor(property_id=p.id, name="Rival Co")
    db.add(comp)
    db.commit()
    topic = AITopic(property_id=p.id, topic_name="Pricing")
    db.add(topic)
    db.commit()
    prompt = AIVisibilityPrompt(
        property_id=p.id, prompt_text="What is the price?", platform="chatgpt",
        topic_id=topic.id,
    )
    db.add(prompt)
    db.commit()

    prev_day = TODAY - timedelta(days=45)
    # Previous period: property was mentioned (had some share).
    for _ in range(3):
        run_query(
            db, p.id, "What is the price?", "chatgpt",
            provider=FR("Opp SoV Court and Rival Co both mentioned."), now=prev_day,
        )
    # Current period: only the competitor is mentioned - property share drops.
    for _ in range(3):
        run_query(
            db, p.id, "What is the price?", "chatgpt",
            provider=FR("Rival Co is the only option mentioned here."), now=TODAY,
        )

    recs = _topic_recommendations(db, p.id, TODAY.date())
    assert any("Close the Share of Voice gap" in r["title"] for r in recs)
    gap_rec = next(r for r in recs if "Close the Share of Voice gap" in r["title"])
    assert gap_rec["state"] == "Actionable"
    assert gap_rec["impact"] == "High"


def test_no_recommendation_for_moderate_stable_topic(db):
    p = _prop(db)
    comp = Competitor(property_id=p.id, name="Rival Co")
    db.add(comp)
    db.commit()
    topic = AITopic(property_id=p.id, topic_name="Neighborhood", priority="medium")
    db.add(topic)
    db.commit()
    prompt = AIVisibilityPrompt(
        property_id=p.id, prompt_text="What is the neighborhood like?",
        platform="chatgpt", topic_id=topic.id,
    )
    db.add(prompt)
    db.commit()

    for _ in range(3):
        run_query(
            db, p.id, "What is the neighborhood like?", "chatgpt",
            provider=FR("Both Opp SoV Court and Rival Co are nearby."), now=TODAY,
        )

    recs = _topic_recommendations(db, p.id, TODAY.date())
    # A stable, non-leading, non-large-gap, non-declining medium-priority
    # topic is Monitor territory - it should not surface as an opportunity.
    assert recs == []


def test_never_reads_prompt_volume_or_demand_fields():
    """The function may explain in its docstring why it avoids demand data;
    what matters is that its executable code never actually reads a
    volume/demand-shaped field. Strip the docstring before scanning so the
    explanation itself doesn't trip the check."""
    import ast
    import inspect

    from app.services.competitor_intelligence import analyzer

    src = inspect.getsource(analyzer._topic_recommendations)
    tree = ast.parse(src)
    func = tree.body[0]
    body_without_docstring = func.body[1:] if ast.get_docstring(func) else func.body
    code_only = "\n".join(ast.unparse(node) for node in body_without_docstring)
    for forbidden in ["volume", "demand", "runs_per_cycle"]:
        assert forbidden not in code_only.lower()


def test_opportunity_engine_surfaces_topic_recommendation_under_competitors_source(db):
    p = _prop(db)
    comp = Competitor(property_id=p.id, name="Rival Co")
    db.add(comp)
    db.commit()
    topic = AITopic(property_id=p.id, topic_name="Amenities", priority="high")
    db.add(topic)
    db.commit()
    prompt = AIVisibilityPrompt(
        property_id=p.id, prompt_text="What amenities?", platform="chatgpt",
        topic_id=topic.id,
    )
    db.add(prompt)
    db.commit()
    for _ in range(3):
        run_query(
            db, p.id, "What amenities?", "chatgpt",
            provider=FR("Opp SoV Court has a great pool."), now=TODAY,
        )

    result = build_opportunities(db, p.id, today=TODAY.date())
    all_opps = result["opportunities"] + result["suppressed"] + result["insufficient"]
    protect_opps = [o for o in all_opps if "Protect" in o["title"]]
    assert protect_opps
    assert protect_opps[0]["source"] == "competitors"
    assert protect_opps[0]["source_label"] == "Competitor IQ"
