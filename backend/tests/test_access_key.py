"""The shared access key after real login arrived: still a valid credential
(scripts, break-glass), still inert when unset and no user exists, and
/api/health stays open for Render's health checks."""

from app.auth.service import create_user
from app.config import settings


def test_no_key_configured_and_no_users_is_open(client):
    assert client.get("/api/companies").status_code == 200


def test_key_required_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "access_key", "s3cret")
    r = client.get("/api/companies")
    assert r.status_code == 401
    assert "sign in" in r.json()["detail"].lower()


def test_correct_key_passes(client, monkeypatch):
    monkeypatch.setattr(settings, "access_key", "s3cret")
    assert client.get("/api/companies", headers={"X-CiteRoll-Key": "s3cret"}).status_code == 200
    assert client.get("/api/companies", headers={"X-CiteRoll-Key": "wrong"}).status_code == 401


def test_health_stays_open(client, monkeypatch):
    monkeypatch.setattr(settings, "access_key", "s3cret")
    assert client.get("/api/health").status_code == 200


def test_a_user_closes_open_mode_even_without_a_key(client, db):
    create_user(db, "first@example.com", "a long enough password")
    assert client.get("/api/companies").status_code == 401
