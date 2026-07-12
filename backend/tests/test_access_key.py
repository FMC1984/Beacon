"""Hosted-deployment access key middleware. Inert locally (no key set);
when BEACON_ACCESS_KEY is set, /api requires the X-Beacon-Key header,
with /api/health exempt so health checks and the key screen still work."""

from app.config import settings


def test_no_key_configured_is_open(client):
    assert client.get("/api/companies").status_code == 200


def test_key_required_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "access_key", "s3cret")
    r = client.get("/api/companies")
    assert r.status_code == 401
    assert "access key" in r.json()["detail"].lower()


def test_correct_key_passes(client, monkeypatch):
    monkeypatch.setattr(settings, "access_key", "s3cret")
    assert client.get("/api/companies", headers={"X-Beacon-Key": "s3cret"}).status_code == 200
    assert client.get("/api/companies", headers={"X-Beacon-Key": "wrong"}).status_code == 401


def test_health_stays_open(client, monkeypatch):
    monkeypatch.setattr(settings, "access_key", "s3cret")
    assert client.get("/api/health").status_code == 200
