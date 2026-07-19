"""Phase 17E: month-end briefing auto-snapshot. Rules: only the PREVIOUS
calendar month is frozen; a month with an existing snapshot is skipped (manual
saves win); a property with no GA4/GSC data in that month is skipped rather
than frozen empty; inactive properties are ignored; the run is idempotent."""

from datetime import date

from app.models import MonthlyBriefing, Property
from app.models.uploads import SourceType
from app.services.reporting_briefing import autosnapshot_closed_months
from tests.test_phase17b_story import _ga4, _gsc, _prop, _upload

# "Today" is July 13, so the closed month under test is June 2026.
TODAY = date(2026, 7, 13)


def _june_data(db, pid):
    gu = _upload(db, pid, SourceType.GSC)
    _gsc(db, pid, gu, date(2026, 6, 10), "some query", 5, 200)


def test_autosnapshot_creates_for_closed_month_with_data(db):
    p = _prop(db, "Auto Court")
    _june_data(db, p.id)
    result = autosnapshot_closed_months(db, today=TODAY)
    assert result["month"] == "2026-06"
    assert p.id in result["created"]

    row = (
        db.query(MonthlyBriefing)
        .filter(MonthlyBriefing.property_id == p.id)
        .one()
    )
    assert row.period_start == date(2026, 6, 1)
    assert row.period_end == date(2026, 6, 30)
    assert row.generated_by == "autosnapshot"
    assert row.payload["period"]["label"] == "June 2026"


def test_autosnapshot_is_idempotent_and_manual_wins(db, client):
    p = _prop(db, "Idem Court")
    _june_data(db, p.id)
    first = autosnapshot_closed_months(db, today=TODAY)
    assert p.id in first["created"]
    second = autosnapshot_closed_months(db, today=TODAY)
    assert p.id in second["skipped_existing"]
    assert db.query(MonthlyBriefing).filter_by(property_id=p.id).count() == 1

    # A manually saved month is likewise never overwritten.
    p2 = _prop(db, "Manual Court")
    _june_data(db, p2.id)
    client.post(f"/api/briefing/generate?property_id={p2.id}&year=2026&month=6")
    before = db.query(MonthlyBriefing).filter_by(property_id=p2.id).one()
    out = autosnapshot_closed_months(db, today=TODAY)
    assert p2.id in out["skipped_existing"]
    after = db.query(MonthlyBriefing).filter_by(property_id=p2.id).one()
    assert after.id == before.id and after.generated_at == before.generated_at


def test_autosnapshot_skips_month_without_data(db):
    p = _prop(db, "Empty Court")  # no GA4/GSC rows at all
    result = autosnapshot_closed_months(db, today=TODAY)
    assert p.id in result["skipped_no_data"]
    assert db.query(MonthlyBriefing).filter_by(property_id=p.id).count() == 0


def test_autosnapshot_skips_inactive_properties(db):
    p = _prop(db, "Retired Court")
    _june_data(db, p.id)
    db.query(Property).filter_by(id=p.id).update({"is_active": False})
    db.commit()
    result = autosnapshot_closed_months(db, today=TODAY)
    assert p.id not in result["created"]
    assert p.id not in result["skipped_existing"]
    assert p.id not in result["skipped_no_data"]


def test_autosnapshot_targets_previous_month_only(db):
    # Data exists only in APRIL; the closed month is June -> skipped as no-data,
    # and no snapshot is invented for April.
    p = _prop(db, "Old Data Court")
    gu = _upload(db, p.id, SourceType.GSC)
    _gsc(db, p.id, gu, date(2026, 4, 10), "old query", 5, 200)
    result = autosnapshot_closed_months(db, today=TODAY)
    assert p.id in result["skipped_no_data"]
    assert db.query(MonthlyBriefing).filter_by(property_id=p.id).count() == 0


def test_autosnapshot_january_rolls_to_december(db):
    p = _prop(db, "Yearroll Court")
    gu = _upload(db, p.id, SourceType.GSC)
    _gsc(db, p.id, gu, date(2026, 12, 10), "december query", 5, 200)
    result = autosnapshot_closed_months(db, today=date(2027, 1, 5))
    assert result["month"] == "2026-12"
    assert p.id in result["created"]


def test_flag_defaults_on():
    from app.config import Settings

    # Default construction (ignoring ambient env): the autosnapshot is ON,
    # because composing is deterministic and free.
    assert Settings(_env_file=None).briefing_autosnapshot is True
