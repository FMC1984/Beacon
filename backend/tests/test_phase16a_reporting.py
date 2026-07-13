"""Phase 16A: reporting foundation. The arithmetic layer under the Reports
section: period windows, comparisons, sampled rates, coverage states, and the
per-source status endpoint. The load-bearing rule everywhere: missing data is
a named state or a null, never a zero."""

from datetime import date

from app.services.reporting import (
    DataState,
    STATE_SEVERITY,
    comparable,
    compare,
    coverage_state,
    pct_change,
    previous_window,
    rate,
)
from tests.test_phase2_uploads import make_property, post_upload


# --- previous_window -------------------------------------------------------


def test_previous_window_is_adjacent_and_equal_length():
    start, end = previous_window(date(2026, 6, 1), date(2026, 6, 30))
    assert (start, end) == (date(2026, 5, 2), date(2026, 5, 31))


def test_previous_window_single_day():
    start, end = previous_window(date(2026, 6, 15), date(2026, 6, 15))
    assert start == end == date(2026, 6, 14)


# --- pct_change / compare --------------------------------------------------


def test_pct_change_normal_and_negative():
    assert pct_change(110, 100) == 0.10
    assert pct_change(75, 100) == -0.25


def test_pct_change_zero_or_missing_baseline_is_null_not_zero():
    assert pct_change(50, 0) is None
    assert pct_change(50, None) is None
    assert pct_change(None, 100) is None


def test_compare_full_envelope():
    c = compare(110, 100)
    assert c == {
        "current": 110,
        "previous": 100,
        "change": 10,
        "pct_change": 0.1,
        "direction": "up",
    }
    assert compare(90, 100)["direction"] == "down"
    assert compare(100, 100)["direction"] == "flat"


def test_compare_missing_side_never_masquerades_as_zero():
    c = compare(None, 100)
    assert c["change"] is None
    assert c["pct_change"] is None
    assert c["direction"] is None
    c = compare(42, None)
    assert c["change"] is None
    assert c["direction"] is None


def test_compare_both_zero_has_no_pct():
    c = compare(0, 0)
    assert c["change"] == 0
    assert c["direction"] == "flat"
    assert c["pct_change"] is None  # 0/0 is not a 0% change


# --- rate ------------------------------------------------------------------


def test_rate_carries_numerator_and_denominator():
    r = rate(8, 21, minimum_sample=3)
    assert r["value"] == round(8 / 21, 4)
    assert (r["numerator"], r["denominator"]) == (8, 21)
    assert r["state"] == DataState.COMPLETE.value


def test_rate_below_minimum_sample_is_null():
    r = rate(2, 2, minimum_sample=3)
    assert r["value"] is None
    assert r["state"] == DataState.INSUFFICIENT_SAMPLE.value


def test_rate_zero_denominator_never_divides():
    r = rate(0, 0)
    assert r["value"] is None
    assert r["state"] == DataState.INSUFFICIENT_SAMPLE.value


# --- coverage_state --------------------------------------------------------

WIN = (date(2026, 6, 1), date(2026, 6, 30))


def test_coverage_not_configured_beats_everything():
    c = coverage_state(*WIN, None, None, configured=False, delay_tolerance_days=3)
    assert c["state"] == DataState.NOT_CONFIGURED.value


def test_coverage_configured_but_no_data_is_awaiting():
    c = coverage_state(*WIN, None, None, configured=True, delay_tolerance_days=3)
    assert c["state"] == DataState.AWAITING_DATA.value


def test_coverage_data_outside_window_is_empty():
    c = coverage_state(
        *WIN, date(2026, 4, 1), date(2026, 4, 30), configured=True, delay_tolerance_days=3
    )
    assert c["state"] == DataState.EMPTY.value
    assert c["covered_start"] is None


def test_coverage_full_window_is_complete():
    c = coverage_state(
        *WIN, date(2026, 5, 1), date(2026, 6, 30), configured=True, delay_tolerance_days=3
    )
    assert c["state"] == DataState.COMPLETE.value
    assert c["covered_start"] == "2026-06-01"
    assert c["covered_end"] == "2026-06-30"


def test_coverage_small_tail_gap_is_delayed_not_partial():
    c = coverage_state(
        *WIN, date(2026, 5, 1), date(2026, 6, 28), configured=True, delay_tolerance_days=3
    )
    assert c["state"] == DataState.SOURCE_DELAYED.value
    assert c["covered_end"] == "2026-06-28"


def test_coverage_big_tail_gap_or_head_gap_is_partial():
    c = coverage_state(
        *WIN, date(2026, 5, 1), date(2026, 6, 20), configured=True, delay_tolerance_days=3
    )
    assert c["state"] == DataState.PARTIAL_PERIOD.value
    c = coverage_state(
        *WIN, date(2026, 6, 10), date(2026, 6, 30), configured=True, delay_tolerance_days=3
    )
    assert c["state"] == DataState.PARTIAL_PERIOD.value
    assert c["covered_start"] == "2026-06-10"


def test_comparable_requires_usable_coverage_on_both_sides():
    complete = {"state": DataState.COMPLETE.value}
    delayed = {"state": DataState.SOURCE_DELAYED.value}
    partial = {"state": DataState.PARTIAL_PERIOD.value}
    assert comparable(complete, complete)["comparable"] is True
    assert comparable(complete, delayed)["comparable"] is True
    verdict = comparable(complete, partial)
    assert verdict["comparable"] is False
    assert verdict["warning"]
    assert "—" not in verdict["warning"]  # no em dashes in copy


def test_every_data_state_has_a_severity():
    assert set(STATE_SEVERITY) == {s.value for s in DataState}


# --- /api/reports endpoints ------------------------------------------------


def test_reports_meta_lists_all_six_tabs(client):
    tabs = client.get("/api/reports/meta").json()["tabs"]
    assert [t["key"] for t in tabs] == [
        "executive",
        "seo",
        "geo",
        "aeo",
        "semantic",
        "content-impact",
    ]
    for t in tabs:
        assert t["label"] and t["summary"] and t["planned_phase"]
        assert t["status"] in ("available", "planned")
        assert "—" not in t["summary"]  # no em dashes in copy


def test_reports_status_unknown_scope_404s(client):
    assert client.get("/api/reports/status?property_id=999").status_code == 404
    assert client.get("/api/reports/status?company_id=999").status_code == 404


def test_reports_status_unconfigured_property_shows_states_not_zeroes(client):
    prop = make_property(client, "Empty Acres")
    body = client.get(f"/api/reports/status?property_id={prop['id']}").json()
    by_key = {s["key"]: s for s in body["sources"]}
    assert set(by_key) == {"ga4", "gsc", "ai_visibility", "reviews", "rag_index"}
    assert by_key["ga4"]["state"] == DataState.NOT_CONFIGURED.value
    assert by_key["gsc"]["state"] == DataState.NOT_CONFIGURED.value
    assert by_key["ai_visibility"]["state"] == DataState.NOT_CONFIGURED.value
    assert by_key["reviews"]["state"] == DataState.NOT_CONFIGURED.value
    # No source ever reports a numeric value here; states carry the story.
    for s in body["sources"]:
        assert s["detail"]
        assert "—" not in s["detail"]


def test_reports_status_reflects_uploaded_data_and_delay(client):
    prop = make_property(client, "Solara Flats")
    post_upload(client, "ga4", prop["id"], "ga4_traffic_with_date.csv")
    body = client.get(f"/api/reports/status?property_id={prop['id']}").json()
    ga4 = next(s for s in body["sources"] if s["key"] == "ga4")
    # Fixture data is June 2026; far older than the manual cadence, so the
    # honest state is delayed, and the date is named.
    assert ga4["state"] == DataState.SOURCE_DELAYED.value
    assert ga4["last_data_date"] == "2026-06-03"
    assert body["worst_state"] == DataState.SOURCE_DELAYED.value


def test_reports_status_scope_isolation(client):
    prop_a = make_property(client, "Alpha Court")
    prop_b = make_property(client, "Beta Lofts")
    post_upload(client, "ga4", prop_a["id"], "ga4_traffic_with_date.csv")
    body_b = client.get(f"/api/reports/status?property_id={prop_b['id']}").json()
    ga4_b = next(s for s in body_b["sources"] if s["key"] == "ga4")
    # Property B must not inherit A's data through the status endpoint.
    assert ga4_b["state"] == DataState.NOT_CONFIGURED.value
    assert ga4_b["last_data_date"] is None
