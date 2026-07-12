"""Phase 12 - AI Visibility Scanner: deterministic analysis, sample-size gating,
source landscape, interpreted hallucination findings, the explainable score, and
context-gated recommendations. Deferred infra items are declared, not built."""

from app.connectors.base import AIVisibilityQueryProvider
from app.models import Property, PropertyProfile
from app.services.ai_visibility import analyze_ai_visibility, run_query
from app.services.ai_visibility.analyzer import _gate
from app.services.ai_visibility.providers import read_queries
from app.services.property_context import get_property_context


class FR(AIVisibilityQueryProvider):
    def __init__(self, response):
        self.response = response

    def execute_query(self, prompt, platform):
        return self.response

    def get_queries(self, db, property_id):
        return read_queries(db, property_id)


def _prop(db, name="Scanner Prop", city="Austin", state="TX", url="https://scanner.com"):
    p = Property(name=name, slug=name.lower().replace(" ", "-"), city=city, state=state, website_url=url)
    db.add(p)
    db.commit()
    return p


def _seed(db, pid, responses):
    for i, resp in enumerate(responses):
        run_query(db, pid, f"q{i}", "chatgpt", provider=FR(resp))


# --- empty + insufficient ---


def test_empty_state(db):
    p = _prop(db)
    a = analyze_ai_visibility(db, p.id)
    assert a["has_queries"] is False
    assert a["score"] is None
    assert a["recommendations"] == []
    assert len(a["deferred"]) == 3  # deferrals are declared, not built


def test_insufficient_sample_gates_score_and_recommends_more(db):
    p = _prop(db, "Thin Prop")
    _seed(db, p.id, ["Thin Prop appears. https://x.com"])  # 1 < 3
    a = analyze_ai_visibility(db, p.id)
    assert a["sample"]["sufficient"] is False
    assert a["score"] is None  # no score from a thin sample
    assert a["mention"]["status"] == "insufficient"
    assert a["recommendations"][0]["state"] == "Insufficient data"


# --- mention + score ---


def test_mention_rate_and_score_when_sufficient(db):
    p = _prop(db, "Solid Prop", url=None)
    _seed(db, p.id, [
        "Solid Prop is a good option.",
        "Consider Solid Prop for your search.",
        "Here are some choices in town.",  # no mention
    ])
    a = analyze_ai_visibility(db, p.id)
    assert a["sample"]["sufficient"] is True
    assert a["mention"]["mentions"] == 2
    assert a["mention"]["rate"] == round(2 / 3, 3)
    # score = mention(66.7*0.6) + fact_consistency(100*0.4) = 40 + 40 = 80
    assert a["score"]["value"] == 80
    assert a["score"]["directional"] is True
    assert len(a["score"]["breakdown"]) == 2


def test_analysis_is_deterministic(db):
    p = _prop(db, "Determinism Prop")
    _seed(db, p.id, ["A. https://a.com", "B. https://b.com", "C https://a.com"])
    import json

    a1 = json.dumps(analyze_ai_visibility(db, p.id), default=str, sort_keys=True)
    a2 = json.dumps(analyze_ai_visibility(db, p.id), default=str, sort_keys=True)
    assert a1 == a2


# --- source landscape + own site ---


def test_source_landscape_and_own_site_cited(db):
    p = _prop(db, "Site Prop", url="https://siteprop.com")
    _seed(db, p.id, [
        "See https://siteprop.com and https://apartments.com",
        "More at https://apartments.com",
        "Also https://apartments.com",
    ])
    a = analyze_ai_visibility(db, p.id)
    landscape = {s["domain"]: s["cited_in_queries"] for s in a["source_landscape"]}
    assert landscape["apartments.com"] == 3
    assert landscape["siteprop.com"] == 1
    assert a["own_site"]["status"] == "cited"


def test_own_site_cannot_verify_without_url(db):
    p = _prop(db, "No URL Prop", url=None)
    _seed(db, p.id, ["x https://a.com", "y https://b.com", "z https://c.com"])
    a = analyze_ai_visibility(db, p.id)
    assert a["own_site"]["status"] == "cannot_verify"


def test_own_site_not_cited_recommendation(db):
    p = _prop(db, "Uncited Prop", url="https://uncited.com")
    _seed(db, p.id, [
        "Uncited Prop is nice. https://apartments.com",
        "Uncited Prop shows up. https://apartments.com",
        "Uncited Prop again. https://apartments.com",
    ])
    a = analyze_ai_visibility(db, p.id)
    assert a["own_site"]["status"] == "not_cited"
    titles = [r["title"] for r in a["recommendations"]]
    assert any("own site cited" in t for t in titles)


# --- fact-check interpretation ---


def test_fact_check_contradiction_becomes_finding_and_rec(db):
    p = _prop(db, "Fact Prop", state="TX")
    _seed(db, p.id, [
        "Fact Prop is located in Denver, Colorado.",
        "Fact Prop is great.",
        "Fact Prop has amenities.",
    ])
    a = analyze_ai_visibility(db, p.id)
    fields = {c["field"] for c in a["fact_checks"]["contradictions"]}
    assert "state" in fields
    assert any("Verify the AI's claim about state" == r["title"] for r in a["recommendations"])


# --- recommendation gating ---


def test_regulated_property_type_contradiction_requires_confirmation(db):
    p = _prop(db, "Regulated Prop")
    db.add(PropertyProfile(property_id=p.id, property_type="affordable", is_regulated=True))
    db.commit()
    _seed(db, p.id, [
        "Regulated Prop is a luxury, high-end community.",
        "Regulated Prop is nice.",
        "Regulated Prop has parking.",
    ])
    a = analyze_ai_visibility(db, p.id)
    type_recs = [r for r in a["recommendations"] if "property type" in r["title"]]
    assert type_recs
    # "luxury" is compliance-sensitive on a regulated property.
    assert all(r["state"] == "Requires confirmation" for r in type_recs)


def test_gate_helper_suppresses_and_confirms(db):
    p = _prop(db)
    db.add(PropertyProfile(
        property_id=p.id, is_regulated=True,
        marketing_restriction_flags=["no_exclusivity_language"],
    ))
    db.commit()
    ctx = get_property_context(db, p.id)
    # Sensitive pricing language on a regulated property -> requires confirmation.
    state, _ = _gate(ctx, "increase visibility for luxury pricing searches")
    assert state == "Requires confirmation"
    # A restricted positioning theme -> suppressed.
    state2, _ = _gate(ctx, "position the community as exclusive and prestigious")
    assert state2 == "Suppressed"


def test_mention_zero_recommendation(db):
    p = _prop(db, "Invisible Prop", url=None)
    _seed(db, p.id, ["Some apartments here.", "Other options.", "More choices."])
    a = analyze_ai_visibility(db, p.id)
    assert a["mention"]["rate"] == 0.0
    assert any("surfaces in AI answers" in r["title"] for r in a["recommendations"])


# --- API ---


def test_analysis_and_analyze_endpoints(client, db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "demo_mode", True)
    pid = client.post("/api/properties", json={"name": "API Scan Prop"}).json()["id"]
    for i in range(3):
        client.post(
            f"/api/ai-visibility/{pid}/query",
            json={"prompt": f"is API Scan Prop good? {i}", "platform": "chatgpt"},
        )
    a = client.get(f"/api/ai-visibility/{pid}/analysis")
    assert a.status_code == 200, a.text
    body = a.json()
    assert body["has_queries"] is True
    assert body["sample"]["sufficient"] is True

    analyze = client.post(f"/api/ai-visibility/{pid}/analyze").json()
    assert analyze["sync_job_id"] is not None


def test_analysis_unknown_property_404(client):
    assert client.get("/api/ai-visibility/9999/analysis").status_code == 404
