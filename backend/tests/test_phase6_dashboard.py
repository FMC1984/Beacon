"""Dashboard metrics API: aggregation, scoping, and the non-negotiable
envelopes (disclosure with every AI figure, provenance with every section)."""

from app.constants import AI_TRAFFIC_DISCLOSURE
from tests.test_phase2_uploads import make_property, post_upload
from tests.test_phase4_gbp_paid import post_paid
from tests.test_phase5_crm import post_crm


def seed_property(client, name="Solara Flats"):
    prop = make_property(client, name)
    post_upload(client, "ga4", prop["id"], "ga4_traffic_with_date.csv")
    post_upload(client, "gsc", prop["id"], "gsc_dates.csv")
    post_upload(client, "gbp", prop["id"], "gbp_performance.csv")
    post_paid(client, prop["id"], "google_ads_campaigns.csv", "google_ads")
    post_crm(client, prop["id"], "crm_yardi_placeholder.csv")
    return prop


def test_dashboard_aggregates_all_sections(client):
    prop = seed_property(client)
    body = client.get(f"/api/dashboard?property_id={prop['id']}&days=30").json()

    ga4 = body["ga4"]
    assert ga4["sessions"] == 1411  # 120+8+45+4+1234
    assert ga4["ai_sessions"] == 12  # chatgpt 8 + perplexity 4
    assert ga4["ai_share"] == round(12 / 1411, 4)
    assert ga4["platform_mix"] == [
        {"platform": "chatgpt", "label": "ChatGPT", "sessions": 8},
        {"platform": "perplexity", "label": "Perplexity", "sessions": 4},
    ]
    assert len(ga4["trend"]) == 3

    assert body["gsc"]["clicks"] == 36
    assert body["gbp"]["search_impressions"] == 165 + 183 + 136
    assert body["paid"]["spend"] == 595.17
    assert body["crm"]["funnel"]["lease"] == 1
    assert body["crm"]["total_leads"] == 3


def test_ai_figures_always_carry_exact_disclosure(client):
    prop = seed_property(client)
    body = client.get(f"/api/dashboard?property_id={prop['id']}").json()
    assert body["ga4"]["disclosure"] == AI_TRAFFIC_DISCLOSURE


def test_every_section_carries_provenance(client):
    prop = seed_property(client)
    body = client.get(f"/api/dashboard?property_id={prop['id']}").json()
    for key in ("ga4", "gsc", "gbp", "paid", "crm"):
        prov = body[key]["provenance"]
        assert prov["source"], key
        assert prov["date_start"] and prov["date_end"], key
        assert prov["last_updated"], key
        # Fixture data is from June 2026; well past the manual-upload cadence.
        assert prov["freshness_warning"], key
        assert "—" not in prov["freshness_warning"]  # no em dashes in copy


def test_window_anchors_to_latest_data(client):
    prop = seed_property(client)
    body = client.get(f"/api/dashboard?property_id={prop['id']}&days=2").json()
    assert body["window"]["end"] == "2026-06-03"
    assert body["window"]["start"] == "2026-06-02"
    assert body["window"]["anchored_to_latest_data"] is True
    # Only June 2-3 GA4 rows: 45 + 4 + 1234
    assert body["ga4"]["sessions"] == 1283


def test_property_scoping_and_portfolio_rollup(client):
    prop_a = seed_property(client, "Alpha Flats")
    prop_b = make_property(client, "Beta Court")
    post_upload(client, "ga4", prop_b["id"], "ga4_combined_source_medium.csv")

    scoped_b = client.get(f"/api/dashboard?property_id={prop_b['id']}").json()
    assert scoped_b["ga4"]["sessions"] == 83
    assert scoped_b["gsc"] is None
    assert scoped_b["crm"] is None

    portfolio = client.get("/api/dashboard").json()
    assert portfolio["ga4"]["sessions"] == 1411 + 83


def test_empty_dashboard_has_null_sections(client):
    prop = make_property(client, "Empty Property")
    body = client.get(f"/api/dashboard?property_id={prop['id']}").json()
    assert all(body[k] is None for k in ("ga4", "gsc", "gbp", "paid", "crm"))


def test_unknown_property_404(client):
    resp = client.get("/api/dashboard?property_id=999")
    assert resp.status_code == 404
