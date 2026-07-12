"""Phase 11.5 AI Visibility Foundation: provider seam + empty state, immutable
raw storage, DETERMINISTIC parsing, per-property rate/budget enforcement, the
context-aware hallucination hook, and the directional RAG chunk Nora cites."""

from datetime import datetime, timedelta, timezone

import pytest

from app.connectors.base import AIVisibilityQueryProvider, AIVisibilityRecord
from app.models import AIVisibilityQuery, Property, PropertyProfile
from app.services.ai_visibility import (
    RateLimitExceeded,
    ai_visibility_summary_text,
    check_response_against_context,
    run_query,
)
from app.services.ai_visibility.parsing import detect_mention, extract_sources
from app.services.ai_visibility.providers import (
    DemoVisibilityProvider,
    read_queries,
)
from app.services.property_context import get_property_context


def _prop(db, name="Solara Flats", city="Tempe", state="AZ"):
    p = Property(name=name, slug=name.lower().replace(" ", "-"), city=city, state=state)
    db.add(p)
    db.commit()
    return p


class FixedResponseProvider(AIVisibilityQueryProvider):
    """Deterministic fake so tests never call an external API and can assert on
    an exact stored response."""

    def __init__(self, response: str):
        self.response = response
        self.calls = 0

    def execute_query(self, prompt: str, platform: str) -> str:
        self.calls += 1
        return self.response

    def get_queries(self, db, property_id):
        return read_queries(db, property_id)


# --- deterministic parsing ---


def test_mention_detection_is_literal_and_negation_unaware():
    text = "Solara Flats is not a great fit for everyone."
    assert detect_mention(text, ["Solara Flats"]) is True  # negation-unaware
    assert detect_mention(text, ["Marlowe"]) is False
    # whole-word: 'Sol' should not match 'Solara'
    assert detect_mention("Solaracorp tower", ["Solar"]) is False


def test_source_extraction_deterministic_and_deduped():
    text = (
        "See https://www.apartments.com/tempe and http://example.org/guide. "
        "Also apartments.com has more. Contact test@nope.com (not a source)."
    )
    a = extract_sources(text)
    b = extract_sources(text)
    assert a == b  # deterministic
    assert "apartments.com" in a  # www stripped, deduped
    assert "example.org" in a


# --- provider seam + empty state ---


def test_empty_state_when_no_queries(db):
    p = _prop(db)
    assert read_queries(db, p.id) == []
    assert ai_visibility_summary_text(db, p.id) is None


def test_provider_get_queries_is_property_scoped(db):
    a = _prop(db, "Alpha")
    b = _prop(db, "Beta")
    prov = FixedResponseProvider("Alpha is worth a look. https://example.com")
    run_query(db, a.id, "best apartments?", "chatgpt", provider=prov)
    assert len(read_queries(db, a.id)) == 1
    assert read_queries(db, b.id) == []


def test_raw_response_stored_verbatim_and_parsed(db):
    p = _prop(db, "Cedar Point")
    resp = "Cedar Point is a solid option. Sources: https://apartments.com/cp"
    prov = FixedResponseProvider(resp)
    row = run_query(db, p.id, "apartments in town?", "chatgpt", provider=prov)
    assert row.raw_response_text == resp  # verbatim
    assert row.brand_mentioned is True
    assert row.sources_cited == ["apartments.com"]


def test_parse_of_stored_text_is_reproducible(db):
    p = _prop(db, "Marlowe")
    resp = "The Marlowe shows up in a few lists. https://x.com/a https://y.org/b"
    prov = FixedResponseProvider(resp)
    r1 = run_query(db, p.id, "q1", "chatgpt", provider=prov)
    r2 = run_query(db, p.id, "q1", "chatgpt", provider=prov)
    assert r1.brand_mentioned == r2.brand_mentioned
    assert r1.sources_cited == r2.sources_cited


# --- rate / budget controls ---


def test_daily_budget_enforced_and_fails_honestly(db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "ai_visibility_daily_limit", 2)
    p = _prop(db, "Budget Prop")
    prov = FixedResponseProvider("ok https://example.com")
    run_query(db, p.id, "q1", "chatgpt", provider=prov)
    run_query(db, p.id, "q2", "chatgpt", provider=prov)
    with pytest.raises(RateLimitExceeded, match="budget reached"):
        run_query(db, p.id, "q3", "chatgpt", provider=prov)


def test_budget_is_per_day(db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "ai_visibility_daily_limit", 1)
    p = _prop(db, "DayProp")
    prov = FixedResponseProvider("ok")
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    run_query(db, p.id, "old", "chatgpt", provider=prov, now=yesterday)
    # Yesterday's query does not count against today's budget.
    run_query(db, p.id, "new", "chatgpt", provider=prov)
    assert len(read_queries(db, p.id)) == 2


def test_invalid_platform_rejected(db):
    p = _prop(db)
    with pytest.raises(ValueError, match="Unknown AI platform"):
        run_query(db, p.id, "q", "bard-9000", provider=FixedResponseProvider("x"))


# --- hallucination-check hook ---


def test_hook_flags_state_contradiction(db):
    p = _prop(db, "Willow Creek", city="Tempe", state="AZ")
    ctx = get_property_context(db, p.id)
    result = check_response_against_context(
        "Willow Creek is located in Denver, Colorado.", p, ctx
    )
    state = next(c for c in result["checks"] if c["field"] == "state")
    assert state["status"] == "contradicted"
    assert result["flags"]


def test_hook_cannot_verify_type_without_context(db):
    p = _prop(db)
    ctx = get_property_context(db, p.id)  # no profile configured
    result = check_response_against_context("A luxury community.", p, ctx)
    ptype = next(c for c in result["checks"] if c["field"] == "property_type")
    assert ptype["status"] == "cannot_verify"
    assert result["context_configured"] is False


def test_hook_flags_type_contradiction_with_context(db):
    p = _prop(db)
    db.add(PropertyProfile(property_id=p.id, property_type="affordable"))
    db.commit()
    ctx = get_property_context(db, p.id)
    result = check_response_against_context(
        "This is a luxury, high-end apartment community.", p, ctx
    )
    ptype = next(c for c in result["checks"] if c["field"] == "property_type")
    assert ptype["status"] == "contradicted"


def test_hook_does_not_infer_missing_facts(db):
    p = _prop(db, state=None)
    ctx = get_property_context(db, p.id)
    result = check_response_against_context("Located in Texas.", p, ctx)
    state = next(c for c in result["checks"] if c["field"] == "state")
    assert state["status"] == "cannot_verify"  # no state on file -> never guesses


# --- RAG chunk + directional language ---


def test_summary_uses_directional_and_insufficient_language(db):
    p = _prop(db, "Directional Prop")
    prov = FixedResponseProvider("Directional Prop appears. https://example.com")
    run_query(db, p.id, "q1", "chatgpt", provider=prov)
    text = ai_visibility_summary_text(db, p.id)
    assert "Insufficient queries to determine visibility" in text
    assert "not a precise visibility percentage" in text
    assert "brand mentioned in 1 of 1" in text


def test_chunk_built_and_scoped(db):
    from app.connectors.development import DevelopmentDataProvider
    from app.services.rag.chunker import build_chunks

    p = _prop(db, "Chunk Prop")
    prov = FixedResponseProvider("Chunk Prop is listed. https://example.com")
    run_query(db, p.id, "q", "chatgpt", provider=prov)
    chunks = build_chunks(
        db, property_id=p.id, sources=["ai_visibility"],
        content_provider=DevelopmentDataProvider(),
    )
    av = [c for c in chunks if c.source == "ai_visibility"]
    assert len(av) == 1
    assert av[0].chroma_id == f"ai_visibility-p{p.id}"
    assert "directional" in av[0].text.lower()


def test_nora_retrieves_ai_visibility_chunk(db, tmp_path):
    from tests.test_phase8_nora import FakeLLM
    from app.services import nora
    from app.services.rag.embedder import DeterministicEmbedder
    from app.services.rag.indexer import build_index

    p = _prop(db, "Nora Vis Prop")
    prov = FixedResponseProvider("Nora Vis Prop shows up in ChatGPT. https://example.com")
    run_query(db, p.id, "how do we show up in chatgpt?", "chatgpt", provider=prov)
    chroma_dir = str(tmp_path / "chroma")
    build_index(db, DeterministicEmbedder(), chroma_dir)
    result = nora.ask(
        db, "How do we show up in ChatGPT?", FakeLLM(), DeterministicEmbedder(),
        property_id=p.id, chroma_dir=chroma_dir,
    )
    assert "ai_visibility" in {c["source_table"] for c in result["citations"]}


# --- API ---


def test_api_execute_list_and_meta(client, db, monkeypatch):
    # Force demo provider so the endpoint does not need an API key.
    from app.config import settings

    monkeypatch.setattr(settings, "demo_mode", True)
    prop = client.post("/api/properties", json={"name": "API Vis Prop"}).json()
    pid = prop["id"]

    meta = client.get("/api/ai-visibility/meta").json()
    assert meta["methodology"]["approach"] == "api"
    assert any(pl["key"] == "chatgpt" for pl in meta["platforms"])

    resp = client.post(
        f"/api/ai-visibility/{pid}/query",
        json={"prompt": "Is API Vis Prop a good option?", "platform": "chatgpt"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["query"]["brand_mentioned"] is True  # demo echoes the prompt
    assert body["budget"]["used_today"] == 1

    listed = client.get(f"/api/ai-visibility/{pid}").json()
    assert len(listed["queries"]) == 1
    qid = listed["queries"][0]["id"]

    single = client.get(f"/api/ai-visibility/{pid}/{qid}").json()
    assert "fact_check" in single
    assert single["query"]["raw_response_text"]


def test_api_rate_limit_returns_429(client, db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "ai_visibility_daily_limit", 1)
    pid = client.post("/api/properties", json={"name": "RL Prop"}).json()["id"]
    client.post(f"/api/ai-visibility/{pid}/query", json={"prompt": "q1", "platform": "chatgpt"})
    resp = client.post(f"/api/ai-visibility/{pid}/query", json={"prompt": "q2", "platform": "chatgpt"})
    assert resp.status_code == 429
    assert "budget reached" in resp.json()["detail"]
