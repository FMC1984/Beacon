"""Google Business Profile reviews: manual CSV import and the live connector.

The manual import is the working path until Google approves API access; the
connector is flag-gated so its restricted scope never joins the shared consent
screen until enabled. All Google HTTP is monkeypatched; no network.
"""

import io

import pytest

from app.config import settings
from app.models import (
    DataConnection,
    OAuthStatus,
    Property,
    PropertyReview,
    SourceType,
    SyncJobStatus,
)
from app.services.google_sync import gapi, oauth
from app.services.google_sync import sync as sync_mod
from app.services.ingestion.common import UploadValidationError
from app.services.ingestion.reviews import parse_reviews_csv


def _prop(db, name="Review Manor"):
    p = Property(name=name, slug=name.lower().replace(" ", "-"))
    db.add(p)
    db.commit()
    return p


# --- manual CSV import --------------------------------------------------------

_CSV = (
    "Reviewer,Rating,Review,Date,Owner response,Review ID\n"
    "Ada L.,5,Loved the location and staff.,2026-06-01,Thank you!,g-abc-1\n"
    "Ben K.,FOUR,Quiet and clean.,2026-06-03,,g-abc-2\n"
    "Cy P.,,,2026-06-04,,g-abc-3\n"  # no body -> skipped
).encode()


def test_parser_is_tolerant_and_skips_bodyless_rows():
    parsed = parse_reviews_csv(_CSV, default_provider="google")
    assert len(parsed.rows) == 2
    assert len(parsed.skipped) == 1
    first = parsed.rows[0]
    assert first["provider"] == "google"
    assert first["rating"] == 5.0
    assert first["author_name"] == "Ada L."
    assert first["response_text"] == "Thank you!"
    assert parsed.rows[1]["rating"] == 4.0  # worded rating


def test_parser_requires_a_body_column():
    with pytest.raises(UploadValidationError):
        parse_reviews_csv(b"Reviewer,Rating,Date\nAda,5,2026-06-01\n", "google")


def test_import_endpoint_upserts_and_is_idempotent(client, db):
    prop = _prop(db)
    files = {"file": ("reviews.csv", io.BytesIO(_CSV), "text/csv")}
    r = client.post(f"/api/reviews/{prop.id}/import", files=files, data={"provider": "google"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["imported"] == 2
    assert body["updated"] == 0
    assert body["skipped"] == 1
    assert body["provider"] == "google"

    # Re-import updates in place (dedup on provider + external_review_id).
    r2 = client.post(
        f"/api/reviews/{prop.id}/import",
        files={"file": ("reviews.csv", io.BytesIO(_CSV), "text/csv")},
        data={"provider": "google"},
    )
    assert r2.json()["imported"] == 0
    assert r2.json()["updated"] == 2
    assert db.query(PropertyReview).filter_by(property_id=prop.id).count() == 2


# --- live connector: scope gating ---------------------------------------------


def test_gbp_scope_absent_by_default_and_present_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "google_gbp_enabled", False)
    assert oauth.GBP_SCOPE not in oauth.current_scopes()
    monkeypatch.setattr(settings, "google_gbp_enabled", True)
    assert oauth.GBP_SCOPE in oauth.current_scopes()


def test_status_reports_gbp_flag_and_hides_source_when_off(client, db, monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "id")
    monkeypatch.setattr(settings, "google_client_secret", "secret")
    monkeypatch.setattr(settings, "google_gbp_enabled", False)
    prop = _prop(db)
    out = client.get(f"/api/google/status?property_id={prop.id}").json()
    assert out["gbp_enabled"] is False


# --- live connector: API normalization + sync ---------------------------------

_FAKE_GBP_PAYLOAD = {
    "reviews": [
        {
            "reviewId": "rid-1",
            "reviewer": {"displayName": "Dana R."},
            "starRating": "FIVE",
            "comment": "Fantastic place to live.",
            "createTime": "2026-05-10T14:03:00.000Z",
            "reviewReply": {"comment": "Thanks Dana!", "updateTime": "2026-05-11T09:00:00Z"},
        },
        {
            "reviewId": "rid-2",
            "reviewer": {"displayName": "Eli M."},
            "starRating": "THREE",
            "comment": "",  # rating-only review, no text
            "createTime": "2026-05-12T00:00:00Z",
        },
    ]
}


def test_gbp_reviews_normalizes_payload(monkeypatch):
    monkeypatch.setattr(gapi, "_request", lambda *a, **k: _FAKE_GBP_PAYLOAD)
    rows = gapi.gbp_reviews("tok", "accounts/1/locations/2")
    assert rows[0]["external_review_id"] == "rid-1"
    assert rows[0]["rating"] == 5.0
    assert rows[0]["review_date"].isoformat() == "2026-05-10"
    assert rows[0]["response_text"] == "Thanks Dana!"
    assert rows[1]["rating"] == 3.0
    assert rows[1]["body"] == ""


def _gbp_connection(db, prop):
    conn = DataConnection(
        property_id=prop.id,
        source_type=SourceType.GBP,
        account_name="tina@example.com",
        external_account_id="tina@example.com",
        oauth_status=OAuthStatus.CONNECTED,
        refresh_token="rt",
        resource_id="accounts/1/locations/2",
        resource_name="Review Manor",
    )
    db.add(conn)
    db.commit()
    return conn


def test_gbp_sync_writes_reviews_and_is_idempotent(client, db, monkeypatch):
    monkeypatch.setattr(settings, "google_gbp_enabled", True)
    monkeypatch.setattr(sync_mod, "refresh_access_token", lambda rt: "at")
    synced_reviews = [
        {
            "external_review_id": "rid-1",
            "author_name": "Dana R.",
            "rating": 5.0,
            "title": None,
            "body": "Fantastic place to live.",
            "review_date": None,
            "response_text": "Thanks Dana!",
            "response_date": None,
            "source_url": None,
        }
    ]
    monkeypatch.setattr(gapi, "gbp_reviews", lambda t, res: synced_reviews)
    prop = _prop(db)
    conn = _gbp_connection(db, prop)

    job = sync_mod.run_google_sync(db, conn.id)
    assert job.status == SyncJobStatus.COMPLETED
    assert job.rows_imported == 1
    reviews = db.query(PropertyReview).filter_by(property_id=prop.id).all()
    assert len(reviews) == 1
    assert reviews[0].provider == "google"
    assert reviews[0].external_review_id == "rid-1"

    # Re-sync updates in place, no duplicate.
    job2 = sync_mod.run_google_sync(db, conn.id)
    assert job2.rows_imported == 0
    assert job2.rows_updated == 1
    assert db.query(PropertyReview).filter_by(property_id=prop.id).count() == 1
