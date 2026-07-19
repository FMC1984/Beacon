"""Phase 16B: SEO Performance report. Fixture data spans two 14-day windows
(previous: June 1-14, current: June 15-28 2026, anchored to the newest GSC
date). The rules under test: honest comparisons, query dedup, deterministic
buckets and flags, threshold-gated movers, and the normalized URL join."""

import pytest

from app.services.ai_query_signals import _norm_path
from app.services.reporting import DataState
from app.services.reporting_seo import (
    MIN_QUERY_IMPRESSIONS,
    seo_recommendations,
)
from tests.test_phase2_uploads import make_property, post_upload

DAYS = 14


@pytest.fixture()
def seo_property(client):
    prop = make_property(client, "Douglas County Housing Partnership")
    post_upload(client, "gsc", prop["id"], "gsc_queries.csv")
    post_upload(client, "ga4", prop["id"], "ga4_organic_landing.csv")
    return prop


def get_report(client, prop, days=DAYS, compare=True):
    res = client.get(
        f"/api/reports/seo?property_id={prop['id']}&days={days}&compare={str(compare).lower()}"
    )
    assert res.status_code == 200
    return res.json()


# --- window + summary --------------------------------------------------------


def test_window_anchors_to_newest_data(client, seo_property):
    body = get_report(client, seo_property)
    assert body["window"]["end"] == "2026-06-28"
    assert body["window"]["start"] == "2026-06-15"
    assert body["previous_window"] == {"start": "2026-06-01", "end": "2026-06-14"}


def test_summary_cards_math_and_sources(client, seo_property):
    cards = {c["key"]: c for c in get_report(client, seo_property)["summary"]["cards"]}
    assert cards["organic_clicks"]["value"] == 27  # sum of current-window rows
    assert cards["organic_impressions"]["value"] == 443
    assert cards["ctr"]["value"] == round(27 / 443, 4)
    assert cards["ctr"]["sample"]["numerator"] == 27
    assert cards["ctr"]["sample"]["denominator"] == 443
    # GA4 organic: chatgpt referral row is excluded, bing organic included.
    assert cards["organic_sessions"]["value"] == 150
    assert cards["organic_engaged_sessions"]["value"] == 85
    assert cards["organic_key_events"]["value"] == 6
    # Key events per session is a RATIO of event counts (events can fire more
    # than once per session), never a "share of sessions converting" and never
    # displayed as a percentage.
    assert cards["organic_conversion_rate"]["value"] == round(6 / 150, 2)
    assert cards["organic_conversion_rate"]["label"] == "Organic key events per session"
    assert cards["organic_conversion_rate"]["unit"] is None
    assert "converting" not in str(cards["organic_conversion_rate"])
    assert cards["organic_sessions"]["source"] == "GA4 (organic medium)"
    assert cards["organic_clicks"]["source"] == "Search Console"
    assert cards["avg_position"]["higher_is_better"] is False


def test_summary_comparison_when_coverage_is_compatible(client, seo_property):
    cards = {c["key"]: c for c in get_report(client, seo_property)["summary"]["cards"]}
    clicks = cards["organic_clicks"]["comparison"]
    assert clicks["previous"] == 29  # 9+9+1+10
    assert clicks["change"] == -2
    sessions = cards["organic_sessions"]["comparison"]
    assert sessions["previous"] == 80
    assert sessions["current"] == 150
    assert sessions["change"] == 70
    assert sessions["pct_change"] == 70 / 80
    assert sessions["direction"] == "up"


def test_summary_no_comparison_without_compare_flag(client, seo_property):
    cards = {
        c["key"]: c
        for c in get_report(client, seo_property, compare=False)["summary"]["cards"]
    }
    assert cards["organic_clicks"]["comparison"] is None
    assert cards["organic_sessions"]["comparison"] is None


def test_missing_previous_coverage_yields_warning_not_numbers(client):
    prop = make_property(client, "Fresh Property")
    # Only current-window rows: the previous window has no coverage at all.
    post_upload(client, "ga4", prop["id"], "ga4_organic_landing.csv")
    body = get_report(client, prop, days=28)  # window reaches back to 06-01
    cards = {c["key"]: c for c in body["summary"]["cards"]}
    ga4 = cards["organic_sessions"]
    assert ga4["comparison"] is None
    assert ga4["comparison_warning"]
    assert "—" not in ga4["comparison_warning"]


# --- trends -------------------------------------------------------------------


def test_trends_daily_series_without_zero_fill(client, seo_property):
    trends = get_report(client, seo_property)["trends"]
    assert trends["state"] == DataState.COMPLETE.value
    dates = [p["date"] for p in trends["series"]]
    # Only dates that actually have rows appear; gaps stay gaps.
    assert dates == ["2026-06-20", "2026-06-28"]
    d28 = trends["series"][1]
    assert d28["clicks"] == 10 + 1 + 3 + 1 + 0
    assert d28["impressions"] == 50 + 25 + 60 + 30 + 3
    assert d28["ctr"] == round(d28["clicks"] / d28["impressions"], 4)


# --- ranking distribution ------------------------------------------------------


def test_ranking_distribution_buckets_and_labels(client, seo_property):
    dist = get_report(client, seo_property)["ranking_distribution"]
    assert dist["state"] == DataState.COMPLETE.value
    buckets = {b["bucket"]: b for b in dist["buckets"]}
    assert buckets["1-3"]["current"] == 1  # branded query at 1.2
    assert buckets["4-10"]["current"] == 2  # income based (6.0), section 8 (9.0)
    assert buckets["11-20"]["current"] == 1  # affordable housing denver (12.0)
    assert buckets["21-50"]["current"] == 2  # near me (25.0), tiny query (40.0)
    assert buckets["51+"]["current"] == 0
    assert dist["total_queries"]["current"] == 6
    assert dist["total_queries"]["previous"] == 3
    assert "not a complete rank-tracking database" in dist["note"]


def test_ranking_distribution_insufficient_without_query_rows(client):
    prop = make_property(client, "Totals Only")
    post_upload(client, "gsc", prop["id"], "gsc_dates.csv")  # date-level only
    dist = get_report(client, prop)["ranking_distribution"]
    assert dist["state"] == DataState.INSUFFICIENT_SAMPLE.value
    assert dist["buckets"] == []


# --- quadrant -------------------------------------------------------------------


def test_quadrant_flags_are_deterministic(client, seo_property):
    quad = get_report(client, seo_property)["quadrant"]
    points = {p["query"]: p for p in quad["points"]}
    # Duplicate suppression: one entry per query even across two pages.
    assert len([q for q in points if q == "affordable housing denver"]) == 1
    assert sorted(points["affordable housing denver"]["pages"]) == [
        "/",
        "/affordable-housing",
    ]
    assert points["income based apartments douglas county"]["flags"][
        "high_impressions_low_ctr"
    ]
    assert points["affordable housing denver"]["flags"]["striking_distance"]
    assert points["section 8 waitlist colorado"]["flags"]["declining"]
    assert not points["douglas county housing partnership"]["flags"]["declining"]
    assert points["douglas county housing partnership"]["branded"] is True
    assert points["affordable housing denver"]["branded"] is False
    assert quad["highlights"]["striking_distance"] == 2  # positions 12.0 and 9.0
    assert quad["rules"]  # classification rules are published, not hidden


# --- movers ---------------------------------------------------------------------


def test_movers_thresholds_suppress_noise(client, seo_property):
    movers = get_report(client, seo_property)["movers"]
    assert movers["state"] == DataState.COMPLETE.value
    gains = {m["query"] for m in movers["gains"]}
    losses = {m["query"] for m in movers["losses"]}
    # +1 click but position improved 3 spots: a gain by the position rule.
    assert "affordable housing denver" in gains
    # -7 clicks: a loss.
    assert "section 8 waitlist colorado" in losses
    # +2 clicks and 0.1 position: below both thresholds, so absent.
    assert "douglas county housing partnership" not in gains | losses
    # 3 impressions max: below the impressions floor, so absent.
    assert "tiny query" not in gains | losses
    assert movers["thresholds"]["min_impressions"] == MIN_QUERY_IMPRESSIONS


def test_movers_require_comparable_previous_period(client, seo_property):
    movers = get_report(client, seo_property, compare=False)["movers"]
    assert movers["state"] == DataState.INSUFFICIENT_SAMPLE.value
    assert movers["gains"] == [] and movers["losses"] == []


# --- landing pages ----------------------------------------------------------------


def test_url_normalization_rules():
    assert _norm_path("https://dchp.org/Affordable-Housing/?ref=x") == "/affordable-housing"
    assert _norm_path("/Affordable-Housing/?ref=x") == "/affordable-housing"
    assert _norm_path("https://dchp.org/") == "/"
    assert _norm_path(None) is None


def test_landing_pages_join_and_unmatched_counts(client, seo_property):
    lp = get_report(client, seo_property)["landing_pages"]
    assert lp["state"] == DataState.COMPLETE.value
    assert lp["match_counts"] == {"matched": 2, "ga4_only": 1, "gsc_only": 1}
    rows = {r["page"]: r for r in lp["rows"]}
    home = rows["/"]  # normalized root
    assert home["matched"] is True
    assert home["sessions"] == 100 and home["clicks"] == 22
    ah = rows["/affordable-housing"]
    assert ah["matched"] is True
    assert ah["sessions"] == 40 and ah["impressions"] == 225
    # Unmatched sides stay null, never zero.
    contact = rows["/contact"]
    assert contact["matched"] is False
    assert contact["clicks"] is None and contact["impressions"] is None
    waitlist = rows["/waitlist"]
    assert waitlist["sessions"] is None and waitlist["clicks"] == 3
    assert "normalized paths" in lp["normalization"]


# --- opportunities integration -----------------------------------------------------


def test_seo_recommendations_deterministic_and_cited(client, seo_property, db):
    recs1 = seo_recommendations(db, seo_property["id"])
    recs2 = seo_recommendations(db, seo_property["id"])
    assert recs1 == recs2  # identical inputs, identical output
    # Fixture has only 2 striking-distance and 1 low-CTR query: below the
    # 3-query floor, no recommendation is fabricated from thin evidence.
    assert recs1 == []


def test_opportunity_engine_includes_seo_source(client, seo_property):
    body = client.get(f"/api/opportunities/{seo_property['id']}").json()
    assert "SEO Performance" in body["by_source"]


def test_seo_report_scope_isolation(client, seo_property):
    other = make_property(client, "Unrelated Property")
    body = get_report(client, other)
    cards = {c["key"]: c for c in body["summary"]["cards"]}
    assert cards["organic_clicks"]["value"] is None
    assert cards["organic_clicks"]["state"] == DataState.NOT_CONFIGURED.value
    assert body["trends"]["series"] == []


def test_seo_report_unknown_property_404s(client):
    assert client.get("/api/reports/seo?property_id=999").status_code == 404
