"""Phase 16C: Executive report, deterministic narrative, and CSV export.

The rules under test: the narrative is deterministic and cited, never makes a
causal claim, and omits what it cannot support; metrics compose the other
modules without recomputation; CSV output is self-describing and client-safe
(no internal RAG metadata); missing values export as their state, not zero."""

import csv
import io

import pytest

from app.services.reporting import DataState
from app.services.reporting_executive import build_executive_report
from tests.test_phase2_uploads import make_property, post_upload

# Causal verbs the narrative must never use (it reports, it does not attribute).
_CAUSAL = ["caused", "because of", "led to", "drove", "resulted in", "thanks to"]


@pytest.fixture()
def exec_property(client):
    prop = make_property(client, "Douglas County Housing Partnership")
    post_upload(client, "gsc", prop["id"], "gsc_queries.csv")
    post_upload(client, "ga4", prop["id"], "ga4_organic_landing.csv")
    return prop


# --- scope + composition ------------------------------------------------------


def test_portfolio_scope_requires_a_property(client, db):
    out = build_executive_report(db, None, days=30)
    assert out["scope_required"] is True
    assert "select a single property" in out["message"].lower()


def test_executive_composes_cards_from_modules(client, exec_property, db):
    out = build_executive_report(db, exec_property["id"], days=14, want_compare=True)
    assert out["scope_required"] is False
    keys = [c["key"] for c in out["cards"]]
    # Organic (SEO), AI referral (dashboard), GEO (visibility), content, opps.
    for expected in [
        "organic_clicks", "organic_impressions", "organic_sessions",
        "organic_key_events", "ai_referral_sessions", "ai_share",
        "ai_mention_rate", "content_score", "actionable_opportunities",
    ]:
        assert expected in keys, expected
    clicks = next(c for c in out["cards"] if c["key"] == "organic_clicks")
    # Same value the SEO report computed for this window.
    assert clicks["value"] == 27
    assert clicks["source"] == "Search Console"


def test_planned_cards_are_honest_states_not_zero(client, exec_property, db):
    out = build_executive_report(db, exec_property["id"], days=14)
    planned = {c["key"]: c for c in out["cards"] if c["key"] in (
        "aeo_readiness_score", "strong_semantic_topics", "cross_source_gaps"
    )}
    assert len(planned) == 3
    for c in planned.values():
        assert c["value"] is None
        assert c["state"] == DataState.NOT_CONFIGURED.value
        assert "arrives with" in c["detail"].lower()


def test_ai_referral_card_carries_disclosure(client, exec_property, db):
    out = build_executive_report(db, exec_property["id"], days=14)
    ai = next(c for c in out["cards"] if c["key"] == "ai_referral_sessions")
    assert "likely higher" in (ai["detail"] or "")


def test_ai_mention_rate_gated_below_minimum(client, exec_property, db):
    # Fixtures include no AI Visibility queries, so mention rate is unconfigured.
    out = build_executive_report(db, exec_property["id"], days=14)
    geo = next(c for c in out["cards"] if c["key"] == "ai_mention_rate")
    assert geo["value"] is None
    assert geo["state"] in (
        DataState.NOT_CONFIGURED.value,
        DataState.INSUFFICIENT_SAMPLE.value,
    )


# --- narrative ----------------------------------------------------------------


def test_narrative_is_deterministic(client, exec_property, db):
    a = build_executive_report(db, exec_property["id"], days=14, want_compare=True)
    b = build_executive_report(db, exec_property["id"], days=14, want_compare=True)
    assert a["narrative"] == b["narrative"]


def test_narrative_sentences_are_cited_and_linked(client, exec_property, db):
    out = build_executive_report(db, exec_property["id"], days=14, want_compare=True)
    assert out["narrative"]
    for item in out["narrative"]:
        assert item["text"]
        assert "link" in item and item["link"]["href"]
        assert isinstance(item["evidence"], list)


def test_narrative_omits_flat_movement_sentences(client, exec_property, db):
    # A metric with no change between periods must not produce a
    # "decreased 0.0 percent from N to N" sentence with equal endpoints.
    import re

    out = build_executive_report(db, exec_property["id"], days=14, want_compare=True)
    for item in out["narrative"]:
        m = re.search(r"from (\d+(?:\.\d+)?) to (\d+(?:\.\d+)?)", item["text"])
        if m:
            assert m.group(1) != m.group(2), item["text"]


def test_ai_referral_comparison_uses_adjacent_window(client, db):
    # Two windows of AI-referral data: the executive AI-referral comparison
    # must contrast the current window with the adjacent previous one, not a
    # doubled window (which would compare a total against itself).
    prop = make_property(client, "AI Referral Co")
    post_upload(client, "ga4", prop["id"], "ga4_organic_landing.csv")
    out = build_executive_report(db, prop["id"], days=14, want_compare=True)
    ai = next(c for c in out["cards"] if c["key"] == "ai_referral_sessions")
    # Current window (Jun 15-28) has the chatgpt referral (8 sessions); the
    # previous window (Jun 1-14) has none, so this is a real gain from 0.
    assert ai["value"] == 8
    assert ai["comparison"]["previous"] == 0


def test_narrative_never_makes_causal_claims(client, exec_property, db):
    out = build_executive_report(db, exec_property["id"], days=14, want_compare=True)
    blob = " ".join(item["text"].lower() for item in out["narrative"])
    for verb in _CAUSAL:
        assert verb not in blob, verb


def test_narrative_has_no_em_dashes(client, exec_property, db):
    out = build_executive_report(db, exec_property["id"], days=14, want_compare=True)
    for item in out["narrative"]:
        assert "—" not in item["text"]


def test_narrative_bare_property_surfaces_only_supported_sentences(client, db):
    # A property with no traffic/visibility data still gets Content IQ's
    # "add content" recommendation, so the narrative honestly reports that
    # single supported sentence rather than inventing performance claims.
    prop = make_property(client, "Bare Property")
    out = build_executive_report(db, prop["id"], days=30)
    assert len(out["narrative"]) == 1
    only = out["narrative"][0]
    assert "add website content" in only["text"].lower()
    assert only["link"]["href"] == "/opportunities"


# --- top actions --------------------------------------------------------------


def test_top_actions_capped_at_three(client, exec_property, db):
    out = build_executive_report(db, exec_property["id"], days=14)
    assert len(out["top_actions"]) <= 3
    for a in out["top_actions"]:
        assert "title" in a and "supporting_signal_count" in a


# --- CSV export ---------------------------------------------------------------


def _rows(text):
    return list(csv.reader(io.StringIO(text)))


def test_executive_csv_is_self_describing(client, exec_property):
    res = client.get(
        f"/api/reports/executive/export.csv?property_id={exec_property['id']}&days=14"
    )
    assert res.status_code == 200
    assert "text/csv" in res.headers["content-type"]
    text = res.text
    assert "Beacon Executive report export" in text
    assert "definition" in text  # the metric-definition column header
    assert "data_status" in text
    # A definition string should be present for a known metric.
    assert "organic search" in text.lower()


def test_seo_csv_missing_value_is_state_not_zero(client):
    prop = make_property(client, "No Data Co")
    res = client.get(f"/api/reports/seo/export.csv?property_id={prop['id']}&days=30")
    assert res.status_code == 200
    rows = _rows(res.text)
    header_idx = next(i for i, r in enumerate(rows) if r and r[0] == "metric")
    body = rows[header_idx + 1 :]
    clicks = next(r for r in body if r and r[0] == "Organic clicks")
    # value column holds the state name, never "0".
    assert clicks[2] == DataState.NOT_CONFIGURED.value
    assert clicks[2] != "0"


def test_csv_excludes_internal_rag_metadata(client, exec_property):
    for section in ("executive", "seo"):
        res = client.get(
            f"/api/reports/{section}/export.csv?property_id={exec_property['id']}&days=14"
        )
        text = res.text.lower()
        for forbidden in ["chunk_id", "chunk id", "vector", "similarity", "embedding", "latency", "retrieval"]:
            assert forbidden not in text, (section, forbidden)


def test_executive_csv_portfolio_scope_400s(client):
    res = client.get("/api/reports/executive/export.csv")
    assert res.status_code == 400


# --- endpoint + isolation -----------------------------------------------------


def test_executive_endpoint_unknown_property_404s(client):
    assert client.get("/api/reports/executive?property_id=999").status_code == 404


def test_executive_scope_isolation(client, exec_property):
    other = make_property(client, "Separate Place")
    out = client.get(f"/api/reports/executive?property_id={other['id']}&days=14").json()
    clicks = next(c for c in out["cards"] if c["key"] == "organic_clicks")
    assert clicks["value"] is None
    assert clicks["state"] == DataState.NOT_CONFIGURED.value


def test_meta_marks_executive_available(client):
    tabs = {t["key"]: t for t in client.get("/api/reports/meta").json()["tabs"]}
    assert tabs["executive"]["status"] == "available"
