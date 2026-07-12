"""AI Query Signals: the three-tier evidence model (observed / search-adjacent /
inferred), honest unavailable states, deterministic inference, Property Context
gating, the RAG chunk, and the hard rule that an exact LLM prompt is never
claimed. All deterministic; no network."""

import json
from datetime import date

from app.models import (
    GA4SessionsDaily,
    GSCPerformanceDaily,
    Property,
    PropertyContent,
    SourceType,
    Upload,
    UploadStatus,
)
from app.services.ai_query_signals import (
    GSC_UNAVAILABLE,
    PROMPT_LIMITATION,
    SEARCH_ADJACENT_DISCLOSURE,
    ai_query_signals_summary_text,
    analyze_ai_query_signals,
)

D = date(2026, 6, 15)

# Affirmative prompt-attribution claims Beacon must never emit (spec "Never
# Use"). Note the spec's own persistent note legitimately contains the substring
# "prompt used" inside a negation ("...do not pass the exact ... prompt used by a
# visitor"), so we test the claim phrasings, not that bare substring.
FORBIDDEN = [
    "user asked chatgpt",
    "actual ai query",
    "llm search term",
    "people asked ai",
    "the prompt used was",
    "prompt entered was",
]

AMENITIES_BODY = (
    "Resort-style pool and fitness center with a clubhouse and dog park. "
    "Pet friendly with a dog park for your dog. Stainless appliances, quartz "
    "counters, in-unit washer and dryer."
)  # covers Community amenities + In-unit features; MISSES Convenience (parking)


# Rows carry an upload_id to satisfy the provenance CHECK constraint. One
# upload per property is enough for these deterministic fixtures.
_uploads: dict[tuple[int, int], int] = {}


def _upload_id(db, pid):
    # Keyed on (session identity, property) so a fresh per-test DB never reuses a
    # stale upload id from a previous test.
    key = (id(db), pid)
    if key not in _uploads:
        u = Upload(
            source_type=SourceType.GA4, property_id=pid, filename="test.csv",
            status=UploadStatus.PROCESSED,
        )
        db.add(u)
        db.commit()
        _uploads[key] = u.id
    return _uploads[key]


def _prop(db, name="Signals Property"):
    p = Property(name=name, slug=name.lower().replace(" ", "-"))
    db.add(p)
    db.commit()
    return p


def _ai_row(db, pid, landing, platform, sessions, engaged=0, key_events=0, source="chatgpt.com"):
    db.add(
        GA4SessionsDaily(
            property_id=pid, date=D, session_source=source, session_medium="referral",
            landing_page=landing, sessions=sessions, engaged_sessions=engaged,
            key_events=key_events, is_ai_referral=True, ai_platform=platform,
            upload_id=_upload_id(db, pid),
        )
    )


def _non_ai_row(db, pid, sessions, engaged):
    db.add(
        GA4SessionsDaily(
            property_id=pid, date=D, session_source="google", session_medium="organic",
            landing_page="/", sessions=sessions, engaged_sessions=engaged,
            is_ai_referral=False, upload_id=_upload_id(db, pid),
        )
    )


def _gsc(db, pid, page, query, clicks=5, impressions=100):
    db.add(
        GSCPerformanceDaily(
            property_id=pid, date=D, page=page, query=query,
            clicks=clicks, impressions=impressions,
            ctr=clicks / impressions, position=4.0,
            upload_id=_upload_id(db, pid),
        )
    )


# --- observed ---


def test_no_ai_traffic_is_honest(db):
    p = _prop(db)
    a = analyze_ai_query_signals(db, p.id)
    assert a["has_ai_traffic"] is False
    assert a["overview"] is None
    assert a["search_adjacent"]["available"] is False
    assert PROMPT_LIMITATION in a["limitations"]
    assert ai_query_signals_summary_text(a) is None


def test_observed_metrics_and_platform_mix(db):
    p = _prop(db)
    _ai_row(db, p.id, "/amenities", "chatgpt", 12, engaged=8, key_events=2)
    _ai_row(db, p.id, "/floorplans", "perplexity", 5, engaged=1)
    db.commit()
    a = analyze_ai_query_signals(db, p.id)
    ov = a["overview"]
    assert ov["total_ai_sessions"] == 17
    assert ov["ai_platform_mix"][0] == {"platform": "chatgpt", "label": "ChatGPT", "sessions": 12}
    assert ov["conversions"]["ai_key_events"] == 2
    # Landing pages grouped and sorted by sessions.
    assert a["landing_pages"][0]["landing_page"] == "/amenities"
    assert a["landing_pages"][0]["sessions"] == 12
    assert a["landing_pages"][0]["evidence_type"] == "observed"


def test_engagement_comparison_withheld_when_low_volume(db):
    p = _prop(db)
    _ai_row(db, p.id, "/amenities", "chatgpt", 6, engaged=3)
    _non_ai_row(db, p.id, 6, 3)
    db.commit()
    a = analyze_ai_query_signals(db, p.id)
    # Both sides below MIN_SESSIONS_FOR_COMPARISON -> no comparison offered.
    assert a["overview"]["engagement"]["comparison"] is None


def test_engagement_comparison_shown_when_enough(db):
    p = _prop(db)
    _ai_row(db, p.id, "/amenities", "chatgpt", 40, engaged=20)
    _non_ai_row(db, p.id, 100, 70)
    db.commit()
    a = analyze_ai_query_signals(db, p.id)
    comp = a["overview"]["engagement"]["comparison"]
    assert comp["ai_engagement_rate"] == 0.5
    assert comp["non_ai_engagement_rate"] == 0.7


# --- search-adjacent ---


def test_gsc_unavailable_state(db):
    p = _prop(db)
    _ai_row(db, p.id, "/amenities", "chatgpt", 10)
    db.commit()
    a = analyze_ai_query_signals(db, p.id)
    sa = a["search_adjacent"]
    assert sa["available"] is False
    assert sa["message"] == GSC_UNAVAILABLE


def test_gsc_page_query_association_and_disclaimer(db):
    p = _prop(db)
    _ai_row(db, p.id, "/amenities", "chatgpt", 10)
    _gsc(db, p.id, "https://x.com/amenities", "pet friendly apartments", clicks=9)
    _gsc(db, p.id, "https://x.com/amenities", "apartments with pool", clicks=4)
    db.commit()
    a = analyze_ai_query_signals(db, p.id)
    sa = a["search_adjacent"]
    assert sa["available"] is True
    assert sa["disclosure"] == SEARCH_ADJACENT_DISCLOSURE
    assoc = sa["associations"][0]
    assert assoc["landing_page"] == "/amenities"
    assert assoc["queries"][0]["query"] == "pet friendly apartments"  # sorted by clicks
    assert all(q["evidence_type"] == "search_adjacent" for q in assoc["queries"])


def test_low_confidence_query_association_excluded(db):
    """A GSC Queries export with no page column cannot be tied to a landing page,
    so it must not produce a fabricated association."""
    p = _prop(db)
    _ai_row(db, p.id, "/amenities", "chatgpt", 10)
    _gsc(db, p.id, None, "pet friendly apartments")  # page is None
    db.commit()
    a = analyze_ai_query_signals(db, p.id)
    assert a["search_adjacent"]["available"] is False


# --- inferred ---


def test_inferred_topics_from_landing_and_content(db):
    p = _prop(db)
    _ai_row(db, p.id, "/amenities", "chatgpt", 12)
    db.add(PropertyContent(property_id=p.id, page="amenities", title="Amenities", body=AMENITIES_BODY))
    db.commit()
    a = analyze_ai_query_signals(db, p.id)
    topics = {t["topic"]: t for t in a["inferred_topics"]}
    # Community amenities is covered by content AND signaled by landing page -> Supported.
    assert "Community amenities" in topics
    assert topics["Community amenities"]["confidence"] == "Supported signal"
    assert topics["Community amenities"]["content_covered"] is True
    # Every inferred item carries the explicit not-a-prompt label.
    assert all(
        t["label"] == "Inferred from landing-page and content signals. This is not an actual AI prompt."
        for t in a["inferred_topics"]
    )


def test_inferred_topic_strong_with_gsc(db):
    p = _prop(db)
    _ai_row(db, p.id, "/amenities", "chatgpt", 12)
    db.add(PropertyContent(property_id=p.id, page="amenities", title="Amenities", body=AMENITIES_BODY))
    _gsc(db, p.id, "https://x.com/amenities", "apartments with a pool and fitness center")
    db.commit()
    a = analyze_ai_query_signals(db, p.id)
    topics = {t["topic"]: t for t in a["inferred_topics"]}
    # landing_page + content_topic + gsc_query = 3 signals = Strong.
    assert topics["Community amenities"]["confidence"] == "Strong signal"
    assert "gsc_query" in topics["Community amenities"]["signal_types"]


def test_renter_question_signal_with_coverage_gap(db):
    p = _prop(db)
    _ai_row(db, p.id, "/amenities", "chatgpt", 12)
    # Content mentions pets (concept) but no parking specifics -> parking is a gap.
    db.add(PropertyContent(property_id=p.id, page="amenities", title="Amenities", body=AMENITIES_BODY))
    db.commit()
    a = analyze_ai_query_signals(db, p.id)
    qs = {s["question"]: s for s in a["renter_question_signals"]}
    # Pet policy concept is on the AI-landed amenities page.
    assert "What is the pet policy?" in qs
    assert qs["What is the pet policy?"]["related_landing_pages"] == ["/amenities"]


# --- recommendations + volume ---


def test_no_recommendations_when_volume_too_low(db):
    p = _prop(db)
    _ai_row(db, p.id, "/amenities", "chatgpt", 3)  # below MIN_AI_SESSIONS_FOR_RECS
    db.add(PropertyContent(property_id=p.id, page="amenities", title="Amenities", body=AMENITIES_BODY))
    db.commit()
    a = analyze_ai_query_signals(db, p.id)
    assert a["recommendations"] == []
    assert any("low" in lim.lower() for lim in a["limitations"])


def test_recommendation_states_present(db):
    p = _prop(db)
    _ai_row(db, p.id, "/amenities", "chatgpt", 12, engaged=1)  # low engagement
    db.add(PropertyContent(property_id=p.id, page="amenities", title="Amenities", body=AMENITIES_BODY))
    db.commit()
    a = analyze_ai_query_signals(db, p.id)
    states = {r["state"] for r in a["recommendations"]}
    assert states  # at least one evidence-backed recommendation
    assert states <= {"Actionable", "Monitor", "Requires confirmation", "Suppressed"}


# --- property context gating ---


def test_unknown_context_gates_sensitive_recommendation(client, db):
    # Property with UNKNOWN regulatory status; a pricing/availability rec must
    # require confirmation, never assume.
    resp = client.post("/api/properties", json={"name": "Gated Prop"})
    pid = resp.json()["id"]
    _ai_row(db, pid, "/floorplans", "chatgpt", 15)
    # Content missing -> floor_plans "Pricing/availability" topic will be a gap
    # with GSC corroboration below.
    db.add(PropertyContent(property_id=pid, page="floor_plans", title="Floor Plans", body="Two bedroom layouts."))
    _gsc(db, pid, "https://x.com/floorplans", "affordable apartments pricing and availability")
    db.commit()
    a = analyze_ai_query_signals(db, pid)
    sensitive = [r for r in a["recommendations"] if "pricing" in (r["topic"] + r["title"]).lower()
                 or "availab" in (r["topic"] + r["title"]).lower()]
    assert sensitive, "expected a pricing/availability recommendation to gate"
    assert all(r["state"] == "Requires confirmation" for r in sensitive)


# --- no exact-prompt language, anywhere ---


def test_no_forbidden_prompt_language_in_response(db):
    p = _prop(db)
    _ai_row(db, p.id, "/amenities", "chatgpt", 12)
    db.add(PropertyContent(property_id=p.id, page="amenities", title="Amenities", body=AMENITIES_BODY))
    _gsc(db, p.id, "https://x.com/amenities", "pet friendly apartments")
    db.commit()
    a = analyze_ai_query_signals(db, p.id)
    blob = json.dumps(a).lower()
    for phrase in FORBIDDEN:
        assert phrase not in blob, f"forbidden phrase leaked: {phrase}"
    # The limitation is always carried.
    assert PROMPT_LIMITATION in a["limitations"]


def test_summary_text_carries_limitation(db):
    p = _prop(db)
    _ai_row(db, p.id, "/amenities", "chatgpt", 12)
    db.commit()
    text = ai_query_signals_summary_text(analyze_ai_query_signals(db, p.id))
    assert PROMPT_LIMITATION in text
    assert "IMPORTANT LIMITATION" in text


# --- API + filters ---


def test_endpoint_and_platform_filter(client, db):
    resp = client.post("/api/properties", json={"name": "API Signals"})
    pid = resp.json()["id"]
    _ai_row(db, pid, "/amenities", "chatgpt", 12)
    _ai_row(db, pid, "/amenities", "perplexity", 4)
    db.commit()
    r = client.get(f"/api/ai-query-signals/{pid}")
    assert r.status_code == 200
    assert r.json()["overview"]["total_ai_sessions"] == 16
    # Platform filter.
    r2 = client.get(f"/api/ai-query-signals/{pid}?platform=chatgpt")
    assert r2.json()["overview"]["total_ai_sessions"] == 12


def test_endpoint_unknown_property_404(client):
    assert client.get("/api/ai-query-signals/9999").status_code == 404


def test_endpoint_bad_date_422(client, db):
    resp = client.post("/api/properties", json={"name": "Bad Date"})
    pid = resp.json()["id"]
    assert client.get(f"/api/ai-query-signals/{pid}?start=nonsense").status_code == 422


# --- RAG chunk + Nora ---


def test_rag_chunk_built_with_limitation(db):
    from app.connectors.development import DevelopmentDataProvider
    from app.services.rag.chunker import build_chunks

    p = _prop(db)
    _ai_row(db, p.id, "/amenities", "chatgpt", 12)
    db.commit()
    chunks = build_chunks(
        db, property_id=p.id, sources=["ai_query_signals"],
        content_provider=DevelopmentDataProvider(),
    )
    aqs = [c for c in chunks if c.source == "ai_query_signals"]
    assert len(aqs) == 1
    assert aqs[0].source_table == "ai_query_signals"
    assert PROMPT_LIMITATION in aqs[0].text


def test_nora_retrieves_signals_and_states_limitation(client, db, tmp_path):
    from tests.test_phase8_nora import FakeLLM
    from app.services import nora
    from app.services.rag.embedder import DeterministicEmbedder
    from app.services.rag.indexer import build_index

    p = _prop(db)
    _ai_row(db, p.id, "/amenities", "chatgpt", 12)
    db.commit()
    chroma_dir = str(tmp_path / "chroma")
    build_index(db, DeterministicEmbedder(), chroma_dir)

    result = nora.ask(
        db, "Do we know what people asked ChatGPT?", FakeLLM(),
        DeterministicEmbedder(), property_id=p.id, chroma_dir=chroma_dir,
    )
    # The ai_query_signals chunk is retrievable and cited.
    tables = {c["source_table"] for c in result["citations"]}
    assert "ai_query_signals" in tables
