"""Phase 16G: Audience geography report.

Where visitors are, from GA4 City / Region. Rules under test: the parser
captures city/region and normalizes GA4's "(not set)" to NULL; sessions GA4
could not place are counted under Unknown and the located share is always
stated; when GA4 rows carry no city at all the report asks for a re-export
rather than showing an empty map; and every AI figure carries the fixed
disclosure.
"""

from pathlib import Path

import pytest

from app.services.ingestion.ga4 import parse_ga4_csv
from app.services.reporting_audience import build_audience_report
from app.services.reporting_executive import build_executive_report
from tests.test_phase2_uploads import make_property, post_upload

_FIXTURE = Path(__file__).parent / "fixtures" / "ga4_city_region.csv"


@pytest.fixture()
def geo_property(client):
    prop = make_property(client, "Beacon Audience Property")
    post_upload(client, "ga4", prop["id"], "ga4_city_region.csv")
    return prop


def test_parser_captures_city_region_and_normalizes_unset():
    result = parse_ga4_csv(_FIXTURE.read_bytes())
    keys = {(r["city"], r["region"]) for r in result.rows}
    assert ("Los Angeles", "California") in keys
    assert ("Phoenix", "Arizona") in keys
    # "(not set)" becomes NULL, never stored as a literal place.
    assert (None, None) in keys
    assert not any(c == "(not set)" for c, _ in keys)


def test_report_aggregates_by_city_with_located_share(client, geo_property, db):
    out = build_audience_report(db, geo_property["id"], days=30)
    assert out["has_data"] and out["geography_available"]
    s = out["summary"]
    assert s["total_sessions"] == 250
    assert s["located_sessions"] == 220
    assert s["located_share"] == round(220 / 250, 4)
    assert s["distinct_cities"] == 3
    assert s["top_city"]["city"] == "Los Angeles"

    cities = {(c["city"], c["region"]): c for c in out["cities"]}
    la = cities[("Los Angeles", "California")]
    assert la["sessions"] == 120  # 100 organic + 20 AI referral
    assert la["ai_sessions"] == 20


def test_unknown_bucket_is_last_and_regionless(client, geo_property, db):
    out = build_audience_report(db, geo_property["id"], days=30)
    assert out["cities"][-1]["city"] == "Unknown"
    unknown = out["cities"][-1]
    assert unknown["sessions"] == 30
    assert unknown["region"] is None
    assert "likely higher" in out["disclosure"]


def test_region_rollup_excludes_unknown(client, geo_property, db):
    out = build_audience_report(db, geo_property["id"], days=30)
    regions = {r["region"]: r for r in out["regions"]}
    assert regions["California"]["sessions"] == 180
    assert regions["Arizona"]["sessions"] == 40
    assert "Unknown" not in regions


def test_geography_unavailable_when_export_has_no_city(client, db):
    prop = make_property(client, "No Geo Property")
    post_upload(client, "ga4", prop["id"], "ga4_organic_landing.csv")
    out = build_audience_report(db, prop["id"], days=365)
    assert out["has_data"] is True
    assert out["geography_available"] is False
    assert "re-export" in out["geography_message"].lower()


def test_no_data_scope_is_named_state_not_zero(client, db):
    prop = make_property(client, "Empty Property")
    out = build_audience_report(db, prop["id"], days=30)
    assert out["has_data"] is False
    assert "upload" in out["message"].lower()


def test_endpoint_and_tab_available(client, geo_property):
    tabs = client.get("/api/reports/meta").json()["tabs"]
    assert any(t["key"] == "audience" and t["status"] == "available" for t in tabs)
    r = client.get(f"/api/reports/audience?property_id={geo_property['id']}&days=30")
    assert r.status_code == 200
    assert r.json()["summary"]["total_sessions"] == 250


def test_csv_export_is_self_describing(client, geo_property):
    r = client.get(
        f"/api/reports/audience/export.csv?property_id={geo_property['id']}&days=30"
    )
    assert r.status_code == 200
    text = r.text
    assert "Los Angeles" in text
    assert "California" in text
    assert "Located share" in text
    assert "likely higher" in text  # disclosure travels with the export


def test_executive_panel_includes_top_cities(client, geo_property, db):
    out = build_executive_report(db, geo_property["id"], days=30)
    tc = out["top_cities"]
    assert tc["available"] is True
    assert tc["cities"][0]["city"] == "Los Angeles"
    assert tc["located_share"] == round(220 / 250, 4)
