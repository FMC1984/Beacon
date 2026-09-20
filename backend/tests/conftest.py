from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import get_db
from app.main import app

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch):
    """Tests must not inherit the developer's backend/.env: no demo mode, no
    real API key. Tests that need either set it explicitly."""
    from app.config import settings

    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "openai_api_key", "")
    for attr in ("gemini_api_key", "anthropic_api_key", "perplexity_api_key"):
        monkeypatch.setattr(settings, attr, "")
    # Auth and billing: tests start in "open mode" (no access key, no users),
    # exactly like a fresh local checkout; tests that want a gate set one up.
    for attr in (
        "access_key", "bootstrap_admin_email", "bootstrap_admin_password", "email_provider",
        "email_api_key", "email_from", "stripe_secret_key", "stripe_webhook_secret",
        "stripe_price_standard", "stripe_price_advanced", "stripe_price_audit", "stripe_portal_return_url",
    ):
        monkeypatch.setattr(settings, attr, "")
    monkeypatch.setattr(settings, "frontend_url", "http://localhost:3100")
    from app.auth.ratelimit import login_limiter, reset_limiter

    login_limiter.clear()
    reset_limiter.clear()


@pytest.fixture()
def test_sessionmaker(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    engine = create_engine(url, connect_args={"check_same_thread": False})
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def client(test_sessionmaker, tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "data"))

    def override_get_db():
        db = test_sessionmaker()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def db(test_sessionmaker):
    session = test_sessionmaker()
    yield session
    session.close()


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()
