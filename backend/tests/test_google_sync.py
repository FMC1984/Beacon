"""Google auto-sync: OAuth state signing, callback connection upsert, resource
selection, sync execution with provenance + classifier + replace-on-overlap,
and honest failure states. All Google HTTP is monkeypatched; no network."""

from datetime import date

import pytest

from app.config import settings
from app.models import (
    DataConnection,
    GA4SessionsDaily,
    GSCPerformanceDaily,
    OAuthStatus,
    Property,
    SourceType,
    SyncJobStatus,
)
from app.services.google_sync import oauth, gapi, sync as sync_mod
from app.services.google_sync.oauth import GoogleOAuthError, sign_state, verify_state


@pytest.fixture(autouse=True)
def google_creds(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "test-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "test-client-secret")


def _prop(db, name="Sync Manor"):
    p = Property(name=name, slug=name.lower().replace(" ", "-"))
    db.add(p)
    db.commit()
    return p


def _connection(db, prop, source, **kw):
    conn = DataConnection(
        property_id=prop.id,
        source_type=source,
        account_name="tina@example.com",
        external_account_id="tina@example.com",
        oauth_status=OAuthStatus.CONNECTED,
        refresh_token="rt-1",
        resource_id=kw.get("resource_id", "properties/123" if source == SourceType.GA4 else "sc-domain:example.org"),
        resource_name=kw.get("resource_name", "Example"),
    )
    db.add(conn)
    db.commit()
    return conn


# --- state signing ---


def test_state_roundtrip():
    s = sign_state(7, now=1000)
    assert verify_state(s, now=1100) == 7


def test_state_tamper_and_expiry_rejected():
    s = sign_state(7, now=1000)
    with pytest.raises(GoogleOAuthError):
        verify_state(s.replace("7.", "8.", 1), now=1100)
    with pytest.raises(GoogleOAuthError):
        verify_state(s, now=1000 + oauth.STATE_TTL_SECONDS + 1)


def test_auth_url_requires_config(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "")
    with pytest.raises(GoogleOAuthError):
        oauth.auth_url(1)


def test_auth_url_requests_offline_consent():
    url = oauth.auth_url(1)
    assert "access_type=offline" in url and "prompt=consent" in url


# --- callback creates connections ---


def test_callback_upserts_both_connections(client, db, monkeypatch):
    p = _prop(db)
    monkeypatch.setattr(
        "app.routers.google.exchange_code",
        lambda code: {"access_token": "at", "refresh_token": "rt-new"},
    )
    monkeypatch.setattr("app.routers.google.account_email", lambda t: "tina@example.com")
    r = client.get(
        "/api/google/callback",
        params={"state": sign_state(p.id), "code": "authcode"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 307)
    assert "google=connected" in r.headers["location"]
    conns = db.query(DataConnection).filter_by(property_id=p.id).all()
    assert {c.source_type for c in conns} == {SourceType.GA4, SourceType.GSC}
    assert all(c.refresh_token == "rt-new" for c in conns)
    assert all(c.oauth_status == OAuthStatus.CONNECTED for c in conns)


def test_callback_rejects_bad_state(client, db):
    r = client.get(
        "/api/google/callback",
        params={"state": "1.999.badsig", "code": "x"},
        follow_redirects=False,
    )
    assert "google=error" in r.headers["location"]


def test_callback_is_exempt_from_access_key(client, db, monkeypatch):
    monkeypatch.setattr(settings, "access_key", "s3cret")
    # No X-Beacon-Key header: still reaches the endpoint (redirects, not 401).
    r = client.get(
        "/api/google/callback",
        params={"state": "malformed", "code": "x"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 307)


# --- sync execution ---


def test_ga4_sync_writes_rows_with_provenance(client, db, monkeypatch):
    p = _prop(db)
    conn = _connection(db, p, SourceType.GA4)
    monkeypatch.setattr(sync_mod, "refresh_access_token", lambda rt: "at")
    monkeypatch.setattr(
        gapi,
        "ga4_run_report",
        lambda t, res, lo, hi: [
            {"date": hi, "session_source": "chatgpt.com", "session_medium": "referral",
             "sessions": 5, "engaged_sessions": 4, "total_users": 5, "key_events": 1},
            {"date": hi, "session_source": "google", "session_medium": "organic",
             "sessions": 40, "engaged_sessions": 30, "total_users": 38, "key_events": 3},
        ],
    )
    r = client.post(f"/api/google/connections/{conn.id}/sync")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed" and body["rows_imported"] == 2

    rows = db.query(GA4SessionsDaily).filter_by(property_id=p.id).all()
    assert len(rows) == 2
    ai = next(r for r in rows if r.session_source == "chatgpt.com")
    assert ai.is_ai_referral is True and ai.ai_platform is not None
    assert all(r.sync_job_id is not None and r.upload_id is None for r in rows)
    db.refresh(conn)
    assert conn.last_sync_at is not None


def test_sync_replaces_overlapping_dates(client, db, monkeypatch):
    p = _prop(db)
    conn = _connection(db, p, SourceType.GA4)
    monkeypatch.setattr(sync_mod, "refresh_access_token", lambda rt: "at")
    payload = [{"date": date.today(), "session_source": "google", "session_medium": "organic",
                "sessions": 10, "engaged_sessions": 8, "total_users": 9, "key_events": 1}]
    monkeypatch.setattr(gapi, "ga4_run_report", lambda t, res, lo, hi: payload)
    client.post(f"/api/google/connections/{conn.id}/sync")
    second = client.post(f"/api/google/connections/{conn.id}/sync").json()
    assert second["rows_replaced"] == 1  # first sync's row was replaced
    assert db.query(GA4SessionsDaily).filter_by(property_id=p.id).count() == 1


def test_gsc_sync_includes_page(client, db, monkeypatch):
    p = _prop(db)
    conn = _connection(db, p, SourceType.GSC)
    monkeypatch.setattr(sync_mod, "refresh_access_token", lambda rt: "at")
    monkeypatch.setattr(
        gapi,
        "gsc_query",
        lambda t, site, lo, hi: [
            {"date": hi, "query": "housing assistance", "page": "https://example.org/apply",
             "clicks": 9, "impressions": 100, "ctr": 0.09, "position": 3.2},
        ],
    )
    r = client.post(f"/api/google/connections/{conn.id}/sync")
    assert r.status_code == 200
    row = db.query(GSCPerformanceDaily).filter_by(property_id=p.id).one()
    assert row.page == "https://example.org/apply" and row.sync_job_id is not None


def test_sync_without_resource_is_a_clear_400(client, db):
    p = _prop(db)
    conn = _connection(db, p, SourceType.GA4, resource_id=None, resource_name=None)
    conn.resource_id = None
    db.commit()
    r = client.post(f"/api/google/connections/{conn.id}/sync")
    assert r.status_code == 400
    assert "No source selected" in r.json()["detail"]


def test_google_failure_recorded_honestly(client, db, monkeypatch):
    p = _prop(db)
    conn = _connection(db, p, SourceType.GA4)
    monkeypatch.setattr(sync_mod, "refresh_access_token", lambda rt: "at")

    def boom(t, res, lo, hi):
        raise GoogleOAuthError("Google returned 403: insufficient permissions")

    monkeypatch.setattr(gapi, "ga4_run_report", boom)
    r = client.post(f"/api/google/connections/{conn.id}/sync")
    assert r.status_code == 502
    db.refresh(conn)
    assert conn.error_message and "403" in conn.error_message
    job = db.query(sync_mod.SyncJob).filter_by(connection_id=conn.id).one()
    assert job.status == SyncJobStatus.FAILED


def test_status_reports_configured_and_connections(client, db):
    p = _prop(db)
    _connection(db, p, SourceType.GA4)
    body = client.get("/api/google/status", params={"property_id": p.id}).json()
    assert body["configured"] is True
    assert len(body["connections"]) == 1
    assert body["connections"][0]["source_type"] == "ga4"


def test_disconnect_keeps_data(client, db, monkeypatch):
    p = _prop(db)
    conn = _connection(db, p, SourceType.GA4)
    monkeypatch.setattr(sync_mod, "refresh_access_token", lambda rt: "at")
    monkeypatch.setattr(
        gapi, "ga4_run_report",
        lambda t, res, lo, hi: [{"date": date.today(), "session_source": "google",
                                 "session_medium": "organic", "sessions": 1,
                                 "engaged_sessions": 1, "total_users": 1, "key_events": 0}],
    )
    client.post(f"/api/google/connections/{conn.id}/sync")
    monkeypatch.setattr("app.routers.google.revoke", lambda rt: None)
    assert client.delete(f"/api/google/connections/{conn.id}").status_code == 200
    db.refresh(conn)
    assert conn.oauth_status == OAuthStatus.REVOKED and conn.refresh_token is None
    # synced rows remain: real history with provenance
    assert db.query(GA4SessionsDaily).filter_by(property_id=p.id).count() == 1
