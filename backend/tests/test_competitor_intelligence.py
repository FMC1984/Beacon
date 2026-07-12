"""Phase 13 Competitor Intelligence: operator-asserted competitor CRUD and
deterministic AI-answer share of voice (sample-gated, alias-aware, gated
recommendations). Deferrals are declared, not built."""

from app.connectors.base import AIVisibilityQueryProvider
from app.models import Competitor, Property, PropertyProfile
from app.services.ai_visibility import run_query
from app.services.ai_visibility.providers import read_queries
from app.services.competitor_intelligence import (
    analyze_share_of_voice,
    competitor_intelligence_summary_text,
)


class FR(AIVisibilityQueryProvider):
    def __init__(self, response):
        self.response = response

    def execute_query(self, prompt, platform):
        return self.response

    def get_queries(self, db, property_id):
        return read_queries(db, property_id)


def _prop(db, name="Compete Prop"):
    p = Property(name=name, slug=name.lower().replace(" ", "-"), city="Austin", state="TX")
    db.add(p)
    db.commit()
    return p


def _competitor(db, pid, name, aliases=None):
    c = Competitor(property_id=pid, name=name, aliases=aliases)
    db.add(c)
    db.commit()
    return c


def _seed_queries(db, pid, responses):
    for i, r in enumerate(responses):
        run_query(db, pid, f"q{i}", "chatgpt", provider=FR(r))


# --- CRUD ---


def test_competitor_crud(client, db):
    pid = client.post("/api/properties", json={"name": "CRUD Prop"}).json()["id"]
    resp = client.post(
        f"/api/competitors/{pid}",
        json={"name": "Rival Flats", "aliases": ["Rival"], "domain": "rival.com"},
    )
    assert resp.status_code == 201, resp.text
    cid = resp.json()["id"]
    assert resp.json()["aliases"] == ["Rival"]

    # duplicate name rejected
    assert client.post(f"/api/competitors/{pid}", json={"name": "Rival Flats"}).status_code == 409

    listed = client.get(f"/api/competitors/{pid}").json()
    assert len(listed) == 1

    client.put(f"/api/competitors/{pid}/{cid}", json={"name": "Rival Flats II"})
    assert client.get(f"/api/competitors/{pid}").json()[0]["name"] == "Rival Flats II"

    assert client.delete(f"/api/competitors/{pid}/{cid}").status_code == 200
    assert client.get(f"/api/competitors/{pid}").json() == []


# --- empty states ---


def test_no_competitors_is_honest(db):
    p = _prop(db)
    a = analyze_share_of_voice(db, p.id)
    assert a["has_competitors"] is False
    assert a["share_of_voice"] == []
    assert competitor_intelligence_summary_text(db, p.id) is None


def test_competitors_but_no_ai_data(db):
    p = _prop(db)
    _competitor(db, p.id, "Rival Flats")
    a = analyze_share_of_voice(db, p.id)
    assert a["has_competitors"] is True
    assert a["has_ai_data"] is False
    assert competitor_intelligence_summary_text(db, p.id) is None


# --- share of voice ---


def test_insufficient_sample_gates_share(db):
    p = _prop(db)
    _competitor(db, p.id, "Rival Flats")
    _seed_queries(db, p.id, ["Compete Prop and Rival Flats."])  # 1 < 3
    a = analyze_share_of_voice(db, p.id)
    assert a["sample"]["sufficient"] is False
    assert a["share_of_voice"]["status"] == "insufficient"
    assert all(e["share"] is None for e in a["share_of_voice"]["entities"])
    assert a["recommendations"][0]["state"] == "Insufficient data"


def test_share_of_voice_math_and_alias(db):
    p = _prop(db, "Compete Prop")
    _competitor(db, p.id, "Rival Flats")
    _competitor(db, p.id, "Peak Apartments", aliases=["Peak Apts"])
    _seed_queries(db, p.id, [
        "Compete Prop and Rival Flats are options.",
        "Rival Flats and Peak Apts are popular.",  # alias hit
        "Consider Rival Flats.",
    ])
    a = analyze_share_of_voice(db, p.id)
    sov = a["share_of_voice"]
    assert sov["sufficient"] is True
    ent = {e["name"]: e for e in sov["entities"]}
    assert ent["Rival Flats"]["mentions"] == 3
    assert ent["Compete Prop"]["mentions"] == 1
    assert ent["Peak Apartments"]["mentions"] == 1  # matched via alias
    assert sov["total_mentions"] == 5
    assert ent["Rival Flats"]["share"] == 0.6
    # entities sorted by mentions desc, property tie-break first
    assert sov["entities"][0]["name"] == "Rival Flats"


def test_analysis_deterministic(db):
    p = _prop(db)
    _competitor(db, p.id, "Rival Flats")
    _seed_queries(db, p.id, ["Rival Flats.", "Compete Prop.", "Rival Flats again."])
    import json

    a1 = json.dumps(analyze_share_of_voice(db, p.id), default=str, sort_keys=True)
    a2 = json.dumps(analyze_share_of_voice(db, p.id), default=str, sort_keys=True)
    assert a1 == a2


def test_recommendation_when_competitor_ahead(db):
    p = _prop(db)
    _competitor(db, p.id, "Rival Flats")
    _seed_queries(db, p.id, ["Rival Flats.", "Rival Flats.", "Rival Flats."])  # property never
    a = analyze_share_of_voice(db, p.id)
    assert any("gap" in r["title"] or "mentioned in AI" in r["title"] for r in a["recommendations"])


def test_recommendation_gated_for_regulated_property(db):
    p = _prop(db)
    db.add(PropertyProfile(property_id=p.id, is_regulated=True))
    db.commit()
    _competitor(db, p.id, "Luxury Towers")
    # Property behind a competitor whose name carries sensitive positioning.
    _seed_queries(db, p.id, ["Luxury Towers.", "Luxury Towers.", "Luxury Towers."])
    a = analyze_share_of_voice(db, p.id)
    # "luxury" is compliance-sensitive -> the gap rec requires confirmation.
    assert any(r["state"] == "Requires confirmation" for r in a["recommendations"])


# --- RAG chunk + directional language ---


def test_summary_directional_language(db):
    p = _prop(db)
    _competitor(db, p.id, "Rival Flats")
    _seed_queries(db, p.id, [
        "Compete Prop and Rival Flats.",
        "Rival Flats.",
        "Rival Flats and Compete Prop.",
    ])
    text = competitor_intelligence_summary_text(db, p.id)
    assert "not a precise market share" in text
    assert "share of voice" in text.lower()


def test_chunk_built_and_scoped(db):
    from app.connectors.development import DevelopmentDataProvider
    from app.services.rag.chunker import build_chunks

    p = _prop(db)
    _competitor(db, p.id, "Rival Flats")
    _seed_queries(db, p.id, ["Rival Flats.", "Compete Prop.", "Rival Flats."])
    chunks = build_chunks(
        db, property_id=p.id, sources=["competitor_intelligence"],
        content_provider=DevelopmentDataProvider(),
    )
    ci = [c for c in chunks if c.source == "competitor_intelligence"]
    assert len(ci) == 1
    assert ci[0].chroma_id == f"competitor_intelligence-p{p.id}"


def test_nora_retrieves_competitor_chunk(db, tmp_path):
    from tests.test_phase8_nora import FakeLLM
    from app.services import nora
    from app.services.rag.embedder import DeterministicEmbedder
    from app.services.rag.indexer import build_index

    p = _prop(db, "Nora Comp Prop")
    _competitor(db, p.id, "Rival Flats")
    _seed_queries(db, p.id, ["Rival Flats.", "Nora Comp Prop.", "Rival Flats."])
    chroma_dir = str(tmp_path / "chroma")
    build_index(db, DeterministicEmbedder(), chroma_dir)
    result = nora.ask(
        db, "Who shows up more than us in ChatGPT?", FakeLLM(),
        DeterministicEmbedder(), property_id=p.id, chroma_dir=chroma_dir,
    )
    assert "competitor_intelligence" in {c["source_table"] for c in result["citations"]}


# --- API ---


def test_analysis_api(client, db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "demo_mode", True)
    pid = client.post("/api/properties", json={"name": "API Comp Prop"}).json()["id"]
    client.post(f"/api/competitors/{pid}", json={"name": "Rival Flats"})
    for i in range(3):
        client.post(
            f"/api/ai-visibility/{pid}/query",
            json={"prompt": f"apartments near API Comp Prop {i}", "platform": "chatgpt"},
        )
    a = client.get(f"/api/competitor-intelligence/{pid}")
    assert a.status_code == 200, a.text
    assert a.json()["has_competitors"] is True
    assert a.json()["sample"]["sufficient"] is True

    analyze = client.post(f"/api/competitor-intelligence/{pid}/analyze").json()
    assert analyze["sync_job_id"] is not None


def test_analysis_unknown_property_404(client):
    assert client.get("/api/competitor-intelligence/9999").status_code == 404
