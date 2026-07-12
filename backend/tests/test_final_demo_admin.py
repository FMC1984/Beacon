"""Final push: demo mode and admin endpoints."""

import pytest

from app.services.nora_llm import DEMO_PREFIX, DemoLLM, get_llm
from app.services.rag.embedder import DeterministicEmbedder, get_embedder
from app.services.rag.indexer import build_index
from tests.test_phase2_uploads import make_property, post_upload


@pytest.fixture()
def demo_settings(monkeypatch, tmp_path):
    from app.config import settings

    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "chroma_dir", str(tmp_path / "chroma"))
    return settings


def test_demo_mode_uses_local_backends(demo_settings):
    assert isinstance(get_llm(), DemoLLM)
    assert isinstance(get_embedder(), DeterministicEmbedder)


def test_demo_llm_is_labeled_and_grounded():
    user = (
        "Data excerpts:\n\n"
        "[1] (ga4_sessions_daily, Solara Flats, 2026-06-01 to 2026-06-04)\n"
        "Property: Solara Flats. Source: GA4.\n"
        "Total sessions: 1564. Key events (conversions): 28.\n"
        "AI referral sessions: 25 (1.6% of sessions).\n\n"
        "Question: how is traffic?"
    )
    answer = DemoLLM().generate("system", user)
    assert answer.startswith(DEMO_PREFIX)
    assert "Total sessions: 1564" in answer
    assert "[1]" in answer
    assert "—" not in answer


def test_demo_ask_end_to_end(demo_settings, client, db):
    prop = make_property(client, "Demo Property")
    post_upload(client, "ga4", prop["id"], "ga4_traffic_with_date.csv")
    build_index(db, DeterministicEmbedder(), demo_settings.chroma_dir)

    resp = client.post(
        "/api/nora/ask",
        json={"question": "How many sessions did we get?", "property_id": prop["id"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "demo"
    assert body["answer"].startswith(DEMO_PREFIX)
    assert body["citations"]  # citations still assembled
    assert body["gate"]["passed"] is False  # gate still computed


def test_admin_status_shape(demo_settings, client):
    body = client.get("/api/admin/status").json()
    assert body["demo_mode"] is True
    assert body["openai_quota"] == "skipped (demo mode)"
    assert body["version"]
    assert body["phase"]
    assert "indexed_chunks" in body["chroma"]
    assert "registry_chunks" in body
    assert "last_index_run" in body
    assert "last_nora_message" in body


def test_admin_reindex_in_demo_mode(demo_settings, client, db):
    prop = make_property(client, "Reindex Property")
    post_upload(client, "ga4", prop["id"], "ga4_traffic_with_date.csv")

    # GA4 chunk + AI Query Signals chunk + Opportunity Engine chunk.
    body = client.post("/api/admin/reindex").json()
    assert body["status"] == "ok"
    assert body["chunks_total"] == 3
    assert body["embedded"] == 3

    status = client.get("/api/admin/status").json()
    assert status["chroma"]["indexed_chunks"] == 3
    assert status["registry_chunks"] == 3
    assert status["last_index_run"]["chunks_total"] == 3


def test_admin_reindex_fails_readably_without_key(client, monkeypatch, tmp_path):
    from app.config import settings

    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "chroma_dir", str(tmp_path / "chroma"))
    body = client.post("/api/admin/reindex").json()
    assert body["status"] == "failed"
    assert "BEACON_OPENAI_API_KEY" in body["error"]
