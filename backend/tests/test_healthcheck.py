"""Admin self-check: every moving part reported as ok/warn/fail with a reason,
and an honest overall roll-up."""

from datetime import datetime, timedelta, timezone

from app.models import DataConnection, OAuthStatus, Property, SourceType


def _names(body):
    return {c["name"]: c for c in body["checks"]}


def test_healthcheck_shape_and_overall(client):
    body = client.get("/api/admin/healthcheck").json()
    assert body["overall"] in ("ok", "warn", "fail")
    checks = _names(body)
    for expected in (
        "Database", "Search index", "Embedding provider", "OpenAI / LLM",
        "Sync queue", "Google auto-sync", "Disk space",
    ):
        assert expected in checks
        assert checks[expected]["status"] in ("ok", "warn", "fail")
        assert checks[expected]["detail"]


def test_database_check_ok(client):
    checks = _names(client.get("/api/admin/healthcheck").json())
    assert checks["Database"]["status"] == "ok"


def test_no_connections_is_ok_not_warn(client):
    checks = _names(client.get("/api/admin/healthcheck").json())
    assert checks["Google auto-sync"]["status"] == "ok"
    assert "manual" in checks["Google auto-sync"]["detail"].lower()


def test_stale_google_connection_warns(client, db):
    p = Property(name="Stale Manor", slug="stale-manor")
    db.add(p)
    db.commit()
    db.add(
        DataConnection(
            property_id=p.id,
            source_type=SourceType.GA4,
            account_name="t@example.com",
            external_account_id="t@example.com",
            oauth_status=OAuthStatus.CONNECTED,
            resource_id="properties/1",
            last_sync_at=datetime.now(timezone.utc) - timedelta(hours=72),
        )
    )
    db.commit()
    body = client.get("/api/admin/healthcheck").json()
    checks = _names(body)
    assert checks["Google auto-sync"]["status"] == "warn"
    assert "ga4" in checks["Google auto-sync"]["detail"].lower()
    assert body["overall"] in ("warn", "fail")


def test_fresh_google_connection_ok(client, db):
    p = Property(name="Fresh Manor", slug="fresh-manor")
    db.add(p)
    db.commit()
    db.add(
        DataConnection(
            property_id=p.id,
            source_type=SourceType.GSC,
            account_name="t@example.com",
            external_account_id="t@example.com",
            oauth_status=OAuthStatus.CONNECTED,
            resource_id="sc-domain:example.org",
            last_sync_at=datetime.now(timezone.utc) - timedelta(hours=3),
        )
    )
    db.commit()
    checks = _names(client.get("/api/admin/healthcheck").json())
    assert checks["Google auto-sync"]["status"] == "ok"
