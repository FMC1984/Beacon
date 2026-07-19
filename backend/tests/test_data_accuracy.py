"""Cross-surface data-accuracy invariants (2026-07-18 audit).

Prompted by two real production catches (the key-events "conversion rate"
mislabel and the GSC anonymized-query undercount): every aggregation rule and
every cross-surface equality is locked here so a future change cannot silently
skew a number on one surface.

Invariants:
- CTR is a ratio of sums, never a mean of daily CTRs.
- Average position is impressions-weighted, never a naive mean.
- "Organic" GA4 metrics include only session_medium organic; referral and AI
  rows are excluded.
- The same seeded window yields IDENTICAL totals on the dashboard, the SEO
  report, the executive report, and the briefing KPIs.
- Audience session totals match the dashboard, and the audience payload
  carries NO users fields (unique users cannot be derived from stored
  aggregates).
- Every GSC total travels with the imported-queries disclosure.
"""

from datetime import date

import pytest

from app.constants import GSC_IMPORTED_QUERIES_DISCLOSURE
from app.models import GA4SessionsDaily, GSCPerformanceDaily, Property, Upload
from app.models.uploads import SourceType, UploadStatus

D1, D2 = date(2026, 6, 1), date(2026, 6, 20)


def _prop(db, name="Accuracy Court"):
    p = Property(name=name, slug=name.lower().replace(" ", "-"), city="Denver", state="CO")
    db.add(p)
    db.commit()
    return p


def _upload(db, pid, source):
    u = Upload(source_type=source, property_id=pid, filename="a.csv",
               status=UploadStatus.PROCESSED, row_count=1)
    db.add(u)
    db.commit()
    return u.id


def _gsc(db, pid, up, d, query, clicks, impressions, position):
    db.add(GSCPerformanceDaily(property_id=pid, upload_id=up, date=d, query=query,
                               page="/p", clicks=clicks, impressions=impressions,
                               ctr=0.0, position=position))
    db.commit()


def _ga4(db, pid, up, d, sessions, engaged, key_events, medium="organic",
         source="google", is_ai=False, platform=None):
    db.add(GA4SessionsDaily(property_id=pid, upload_id=up, date=d,
                            session_source=source, session_medium=medium,
                            sessions=sessions, engaged_sessions=engaged,
                            total_users=sessions, key_events=key_events,
                            is_ai_referral=is_ai, ai_platform=platform))
    db.commit()


@pytest.fixture()
def seeded(db):
    """One property, one month, both sources sharing the same latest date so
    every anchored 30-day window coincides across surfaces.

    GSC: clicks 12, impressions 400 -> CTR 0.03 exactly;
         weighted position (5*100 + 15*300)/400 = 12.5 (naive mean would be 10).
    GA4 organic: sessions 150, engaged 90, key events 15 -> 0.10/session.
    GA4 non-organic: a referral row (7 sessions, AI) excluded from organic.
    """
    p = _prop(db)
    gu = _upload(db, p.id, SourceType.GSC)
    au = _upload(db, p.id, SourceType.GA4)
    _gsc(db, p.id, gu, D1, "q1", 10, 100, 5.0)
    _gsc(db, p.id, gu, D2, "q1", 2, 300, 15.0)
    _ga4(db, p.id, au, D1, 50, 30, 5)
    _ga4(db, p.id, au, D2, 100, 60, 10)
    _ga4(db, p.id, au, D2, 7, 4, 1, medium="referral", source="chatgpt.com",
         is_ai=True, platform="chatgpt")
    return p


def _seo_cards(client, pid):
    body = client.get(f"/api/reports/seo?property_id={pid}&days=30").json()
    return {c["key"]: c for c in body["summary"]["cards"]}, body


# --- aggregation rules --------------------------------------------------------


def test_ctr_is_ratio_of_sums_not_mean_of_daily_ctrs(client, db, seeded):
    cards, _ = _seo_cards(client, seeded.id)
    # Ratio of sums: 12/400 = 0.03. Mean of daily CTRs would be
    # (10/100 + 2/300)/2 = 0.0533 - a different, wrong number.
    assert cards["ctr"]["value"] == pytest.approx(0.03)
    assert cards["organic_clicks"]["value"] == 12
    assert cards["organic_impressions"]["value"] == 400


def test_average_position_is_impressions_weighted(client, db, seeded):
    cards, _ = _seo_cards(client, seeded.id)
    # Weighted: (5*100 + 15*300)/400 = 12.5. Naive mean would be 10.0.
    assert cards["avg_position"]["value"] == pytest.approx(12.5)


def test_organic_metrics_exclude_referral_and_ai_rows(client, db, seeded):
    cards, _ = _seo_cards(client, seeded.id)
    assert cards["organic_sessions"]["value"] == 150  # not 157
    assert cards["organic_engaged_sessions"]["value"] == 90
    assert cards["organic_key_events"]["value"] == 15
    assert cards["organic_conversion_rate"]["value"] == pytest.approx(0.10)


# --- cross-surface equality ---------------------------------------------------


def test_dashboard_and_seo_report_agree_on_totals(client, db, seeded):
    cards, _ = _seo_cards(client, seeded.id)
    dash = client.get(f"/api/dashboard?property_id={seeded.id}&days=30").json()
    assert dash["gsc"]["clicks"] == cards["organic_clicks"]["value"]
    assert dash["gsc"]["impressions"] == cards["organic_impressions"]["value"]
    assert dash["gsc"]["ctr"] == pytest.approx(cards["ctr"]["value"])
    assert dash["gsc"]["avg_position"] == pytest.approx(cards["avg_position"]["value"], abs=0.1)
    # Dashboard sessions are ALL mediums; organic is a strict subset.
    assert dash["ga4"]["sessions"] == 157
    assert dash["ga4"]["ai_sessions"] == 7


def test_executive_and_briefing_agree_with_seo_report(client, db, seeded):
    cards, _ = _seo_cards(client, seeded.id)
    execu = client.get(
        f"/api/reports/executive?property_id={seeded.id}&days=30"
    ).json()
    exec_cards = {c["key"]: c for c in execu["cards"]}
    assert exec_cards["organic_clicks"]["value"] == cards["organic_clicks"]["value"]
    assert exec_cards["organic_sessions"]["value"] == cards["organic_sessions"]["value"]

    briefing = client.get(
        f"/api/briefing?property_id={seeded.id}&year=2026&month=6"
    ).json()
    kpis = {k["key"]: k for k in briefing["kpis"]}
    if "organic_clicks" in kpis:
        assert kpis["organic_clicks"]["value"] == cards["organic_clicks"]["value"]


def test_audience_sessions_match_dashboard(client, db, seeded):
    dash = client.get(f"/api/dashboard?property_id={seeded.id}&days=30").json()
    aud = client.get(f"/api/reports/audience?property_id={seeded.id}&days=30").json()
    assert aud["has_data"] is True
    assert aud["summary"]["total_sessions"] == dash["ga4"]["sessions"]
    assert aud["summary"]["ai_sessions"] == dash["ga4"]["ai_sessions"]


# --- no unsupportable users numbers ------------------------------------------


def test_audience_payload_has_no_users_fields(client, db, seeded):
    aud = client.get(f"/api/reports/audience?property_id={seeded.id}&days=30").json()
    import json

    blob = json.dumps(aud)
    # Unique users cannot be derived from the stored per-dimension aggregates,
    # so no surface may display a "users" number.
    assert '"users"' not in blob
    assert '"total_users"' not in blob


# --- GSC undercount disclosure -----------------------------------------------


def test_gsc_totals_carry_imported_queries_disclosure(client, db, seeded):
    _, body = _seo_cards(client, seeded.id)
    assert body["summary"]["gsc_note"] == GSC_IMPORTED_QUERIES_DISCLOSURE
    assert "anonymized" in body["summary"]["gsc_note"]
    assert "—" not in body["summary"]["gsc_note"]  # no em dashes in copy

    csv = client.get(
        f"/api/reports/seo/export.csv?property_id={seeded.id}&days=30"
    ).text
    assert "anonymized queries" in csv
