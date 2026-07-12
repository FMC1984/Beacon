from datetime import date

import pytest

from app.services.ingestion.common import UploadValidationError, parse_ctr
from app.services.ingestion.ga4 import parse_ga4_csv
from app.services.ingestion.gsc import parse_gsc_csv
from tests.conftest import fixture_bytes


def test_ga4_parses_ui_export_with_preamble():
    result = parse_ga4_csv(fixture_bytes("ga4_traffic_with_date.csv"))
    assert len(result.rows) == 5
    first = result.rows[0]
    assert first["date"] == date(2026, 6, 1)
    assert first["session_source"] == "google"
    assert first["session_medium"] == "organic"
    assert first["sessions"] == 120
    # "(not set)" campaigns are kept verbatim; classification is Phase 3's job.
    assert first["session_campaign"] == "(not set)"


def test_ga4_totals_row_skipped_and_commas_parsed():
    result = parse_ga4_csv(fixture_bytes("ga4_traffic_with_date.csv"))
    # Line numbers are real file lines (preamble counted): header is line 7,
    # data is 8-12, the Grand total row is line 13.
    assert result.skipped == [{"line": 13, "reason": "totals row"}]
    direct = [r for r in result.rows if r["session_source"] == "(direct)"][0]
    assert direct["sessions"] == 1234


def test_ga4_combined_source_medium_split():
    result = parse_ga4_csv(fixture_bytes("ga4_combined_source_medium.csv"))
    copilot = result.rows[1]
    assert copilot["session_source"] == "copilot.microsoft.com"
    assert copilot["session_medium"] == "referral"
    # "Conversions" header (old GA4 name) maps onto key_events.
    assert result.rows[0]["key_events"] == 4


def test_ga4_missing_date_rejected_with_instructions():
    with pytest.raises(UploadValidationError, match="Date"):
        parse_ga4_csv(fixture_bytes("ga4_missing_date.csv"))


def test_gsc_dates_export_parses():
    result = parse_gsc_csv(fixture_bytes("gsc_dates.csv"))
    assert len(result.rows) == 3
    assert result.rows[0]["date"] == date(2026, 6, 1)
    assert result.rows[0]["clicks"] == 12
    assert result.rows[0]["ctr"] == pytest.approx(0.0353)
    assert result.rows[0]["query"] is None


def test_gsc_query_level_with_date_parses():
    result = parse_gsc_csv(fixture_bytes("gsc_queries_with_date.csv"))
    assert result.rows[0]["query"] == "apartments in tempe az"
    # Fractional CTR (API style) passes through unscaled.
    assert result.rows[0]["ctr"] == pytest.approx(0.0417)


def test_gsc_no_date_rejected_with_instructions():
    with pytest.raises(UploadValidationError, match="Dates tab"):
        parse_gsc_csv(fixture_bytes("gsc_queries_no_date.csv"))


def test_gsc_queries_with_preamble_range_accepted_as_snapshot():
    # Real GA4 "Reports > Search Console > Queries" export: no Date column,
    # but the file's own preamble carries Start date/End date. Google's UI
    # cannot export Query + Date together, so this is accepted as a period
    # total rather than rejected.
    result = parse_gsc_csv(fixture_bytes("gsc_queries_dchp_no_date.csv"))
    assert result.snapshot_period == (date(2026, 6, 1), date(2026, 6, 30))
    assert len(result.rows) == 678
    top = max(result.rows, key=lambda r: r["clicks"])
    assert top["query"] == "douglas county housing partnership"
    assert top["clicks"] == 95
    # Every row is stamped with the period end, never faked as daily.
    assert all(r["date"] == date(2026, 6, 30) for r in result.rows)


def test_ctr_normalization():
    assert parse_ctr("3.53%") == pytest.approx(0.0353)
    assert parse_ctr("0.0417") == pytest.approx(0.0417)
    assert parse_ctr("") == 0.0
