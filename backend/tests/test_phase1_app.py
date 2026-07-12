from fastapi.testclient import TestClient

from app.constants import AI_TRAFFIC_DISCLOSURE
from app.main import app


def test_health_endpoint():
    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "database": "reachable"}


def test_disclosure_copy_is_exact():
    # Fixed by the PRD (4.2); a drive-by edit here would silently change every
    # AI traffic surface in the app.
    assert AI_TRAFFIC_DISCLOSURE == (
        "This reflects AI traffic that passed referrer data. "
        "Actual AI-influenced traffic is likely higher."
    )


def test_disclosure_has_no_em_dash():
    assert "—" not in AI_TRAFFIC_DISCLOSURE
