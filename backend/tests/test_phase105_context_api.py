"""Property context CRUD, vocabulary validation, honest unspecified defaults,
and program-status integrity through the API."""

from app.models import RagSyncJob
from app.services.property_context import config
from tests.test_phase2_uploads import make_property


def put_ctx(client, property_id, **fields):
    return client.put(f"/api/property-context/{property_id}", json=fields)


def test_vocabulary_endpoint():
    from fastapi.testclient import TestClient
    from app.main import app

    body = TestClient(app).get("/api/property-context/vocabulary").json()
    assert set(body["property_types"]) == set(config()["property_types"])
    assert "LIHTC" in body["regulatory_programs"]


def test_unconfigured_property_is_unspecified(client):
    prop = make_property(client, "Blank Context")
    body = client.get(f"/api/property-context/{prop['id']}").json()
    assert body["configured"] is False
    assert body["property_type"] is None
    assert body["is_regulated"] is None
    assert body["effective_regulatory"] == "unknown"


def test_upsert_and_read(client):
    prop = make_property(client, "Configured Context")
    resp = put_ctx(
        client, prop["id"], property_type="student", target_audience="ASU students",
        is_regulated=False, regulatory_programs=[], marketing_restriction_flags=[],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["property_type"] == "student"
    assert body["effective_regulatory"] == "not_regulated"
    assert body["configured"] is True


def test_three_state_regulatory_persists(client):
    prop = make_property(client, "Three State")
    # None (unknown) is the honest default and must persist as null.
    put_ctx(client, prop["id"], property_type="conventional", is_regulated=None)
    body = client.get(f"/api/property-context/{prop['id']}").json()
    assert body["is_regulated"] is None
    assert body["effective_regulatory"] == "unknown"


def test_invalid_property_type_rejected(client):
    prop = make_property(client, "Bad Type")
    resp = put_ctx(client, prop["id"], property_type="penthouse")
    assert resp.status_code == 422
    assert "Invalid property_type" in resp.json()["detail"]


def test_invalid_program_rejected(client):
    prop = make_property(client, "Bad Program")
    resp = put_ctx(client, prop["id"], regulatory_programs=["MADE_UP"])
    assert resp.status_code == 422
    assert "Invalid regulatory program" in resp.json()["detail"]


def test_invalid_flag_rejected(client):
    prop = make_property(client, "Bad Flag")
    resp = put_ctx(client, prop["id"], marketing_restriction_flags=["nope"])
    assert resp.status_code == 422


def test_context_edit_enqueues_sync(client, db):
    prop = make_property(client, "Context Sync")
    put_ctx(client, prop["id"], property_type="senior", is_regulated=True)
    job = db.query(RagSyncJob).order_by(RagSyncJob.id.desc()).first()
    assert job.source == "property_context"
    assert job.reason == "context_edit"


def test_fail_safe_via_api(client):
    prop = make_property(client, "Fail Safe")
    # is_regulated left null but a program set -> effective regulated.
    put_ctx(client, prop["id"], regulatory_programs=["LIHTC"])
    body = client.get(f"/api/property-context/{prop['id']}").json()
    assert body["is_regulated"] is None
    assert body["effective_regulatory"] == "regulated"
