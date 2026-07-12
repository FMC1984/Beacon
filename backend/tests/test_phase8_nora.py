"""Phase 8: correlation gate, Nora response assembly, citations, persistence.
All local: DeterministicEmbedder + FakeLLM, no network calls."""

from datetime import date

import pytest

from app.constants import AI_TRAFFIC_DISCLOSURE
from app.models import (
    GA4SessionsDaily,
    LeadStatus,
    CRMLead,
    MessageRole,
    NoraMessage,
    SourceType,
    Upload,
)
from app.services import nora
from app.services.correlation import (
    can_claim_correlation,
    compute_correlation_inputs,
)
from app.services.rag.embedder import DeterministicEmbedder
from app.services.rag.indexer import build_index
from tests.test_phase2_uploads import make_property, post_upload
from tests.test_phase5_crm import post_crm


class FakeLLM:
    def __init__(self, reply="Grounded answer [1]."):
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    def generate(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.reply


class ExplodingLLM:
    def generate(self, system: str, user: str) -> str:
        raise AssertionError("LLM must not be called on this path")


@pytest.fixture()
def seeded(client, db, tmp_path):
    prop = make_property(client, "Solara Flats")
    post_upload(client, "ga4", prop["id"], "ga4_traffic_with_date.csv")
    post_crm(client, prop["id"], "crm_yardi_placeholder.csv")
    chroma_dir = str(tmp_path / "chroma")
    build_index(db, DeterministicEmbedder(), chroma_dir)
    return prop, chroma_dir


# --- gate function (hard rule 5, exact semantics) ---


def test_gate_thresholds():
    assert can_claim_correlation(30, 5, 0.5, 2) is True
    assert can_claim_correlation(30, 5, -0.6, 2) is True  # negative r counts
    assert can_claim_correlation(29, 5, 0.5, 2) is False
    assert can_claim_correlation(30, 4, 0.5, 2) is False
    assert can_claim_correlation(30, 5, 0.49, 2) is False
    assert can_claim_correlation(30, 5, 0.5, 1) is False


def test_correlation_inputs_from_thin_data(seeded, db):
    ci = compute_correlation_inputs(db, 1)
    assert ci.ai_sessions == 12
    assert ci.leases == 1
    assert ci.periods_confirmed == 1  # only 2026-06 has both GA4 and CRM data
    assert ci.r == 0.0  # undefined with a single period


def seed_gate_passing_data(db, property_id):
    upload = Upload(
        source_type=SourceType.GA4, filename="synthetic.csv", property_id=property_id
    )
    db.add(upload)
    db.flush()
    for month, ai_sessions, leases in ((4, 18, 2), (5, 22, 4), (6, 40, 5)):
        db.add(
            GA4SessionsDaily(
                property_id=property_id,
                upload_id=upload.id,
                date=date(2026, month, 15),
                session_source="chatgpt.com",
                session_medium="referral",
                sessions=ai_sessions,
                is_ai_referral=True,
                ai_platform="chatgpt",
            )
        )
        for i in range(leases):
            db.add(
                CRMLead(
                    property_id=property_id,
                    upload_id=upload.id,
                    external_lead_id=f"S-{month}-{i}",
                    lead_source_raw="synthetic",
                    status=LeadStatus.LEASE,
                    first_contact_date=date(2026, month, 1),
                    lease_signed_date=date(2026, month, 20),
                )
            )
    db.commit()


def test_correlation_inputs_pass_with_enough_data(client, db):
    prop = make_property(client, "Gate Property")
    seed_gate_passing_data(db, prop["id"])
    ci = compute_correlation_inputs(db, prop["id"])
    assert ci.ai_sessions == 80
    assert ci.leases == 11
    assert ci.periods_confirmed == 3
    assert abs(ci.r) >= 0.5
    assert can_claim_correlation(ci.ai_sessions, ci.leases, ci.r, ci.periods_confirmed)


# --- response assembly ---


def test_correlation_question_failed_gate_uses_template_no_llm(seeded, db):
    prop, chroma_dir = seeded
    result = nora.ask(
        db,
        "Is our ChatGPT traffic converting into leases?",
        ExplodingLLM(),  # proves the model is never called on this path
        DeterministicEmbedder(),
        property_id=prop["id"],
        chroma_dir=chroma_dir,
    )
    assert result["gate"]["passed"] is False
    assert "not enough data yet" in result["answer"].lower()
    assert "currently 12" in result["answer"]  # actual AI sessions in the message
    assert result["disclosure"] == AI_TRAFFIC_DISCLOSURE
    assert "—" not in result["answer"]


def test_normal_question_generates_with_citations(seeded, db):
    prop, chroma_dir = seeded
    llm = FakeLLM(reply="June traffic was 1411 sessions [1] — mostly direct.")
    result = nora.ask(
        db,
        "How much traffic did Solara Flats get in June?",
        llm,
        DeterministicEmbedder(),
        property_id=prop["id"],
        chroma_dir=chroma_dir,
    )
    assert len(llm.calls) == 1
    system, user = llm.calls[0]
    assert "must NOT claim" in system  # failed gate forbids correlation talk
    assert "Data excerpts" in user and "[1]" in user
    # Citations come from the registry, not the model.
    assert result["citations"]
    assert all(
        c["source_ref"].startswith(("ga4", "crm", "ai_query_signals", "opportunity_engine"))
        for c in result["citations"]
    )
    # Em dash from the model is sanitized in code.
    assert "—" not in result["answer"]
    assert "1411 sessions [1], mostly direct" in result["answer"]


def test_gate_passed_prompt_carries_verified_stats(client, db, tmp_path):
    prop = make_property(client, "Gate Property")
    seed_gate_passing_data(db, prop["id"])
    chroma_dir = str(tmp_path / "chroma")
    build_index(db, DeterministicEmbedder(), chroma_dir)

    llm = FakeLLM()
    result = nora.ask(
        db,
        "Is AI traffic correlated with leases here?",
        llm,
        DeterministicEmbedder(),
        property_id=prop["id"],
        chroma_dir=chroma_dir,
    )
    assert result["gate"]["passed"] is True
    assert result["gate"]["unmet"] == []
    system, _ = llm.calls[0]
    assert "code-verified correlation" in system
    assert "Never present it as" in system and "causation" in system


def test_conversation_persistence(seeded, db):
    prop, chroma_dir = seeded
    result = nora.ask(
        db,
        "What does the CRM data show?",
        FakeLLM(),
        DeterministicEmbedder(),
        property_id=prop["id"],
        chroma_dir=chroma_dir,
    )
    messages = (
        db.query(NoraMessage)
        .filter_by(conversation_id=result["conversation_id"])
        .order_by(NoraMessage.id)
        .all()
    )
    assert [m.role for m in messages] == [MessageRole.USER, MessageRole.ASSISTANT]
    assert messages[1].citations == result["citations"]
    assert messages[1].gate_passed is False

    # Follow-up lands in the same conversation.
    nora.ask(
        db,
        "And the traffic?",
        FakeLLM(),
        DeterministicEmbedder(),
        property_id=prop["id"],
        conversation_id=result["conversation_id"],
        chroma_dir=chroma_dir,
    )
    assert (
        db.query(NoraMessage)
        .filter_by(conversation_id=result["conversation_id"])
        .count()
        == 4
    )


def test_empty_index_gives_no_data_answer(client, db, tmp_path):
    prop = make_property(client, "Empty Property")
    result = nora.ask(
        db,
        "How is traffic trending?",
        ExplodingLLM(),
        DeterministicEmbedder(),
        property_id=prop["id"],
        chroma_dir=str(tmp_path / "chroma-empty"),
    )
    assert result["answer"] == nora.NO_DATA_ANSWER
    assert result["citations"] == []


def test_sanitize_strips_em_dashes():
    assert nora.sanitize("AI traffic — mostly ChatGPT — grew.") == (
        "AI traffic, mostly ChatGPT, grew."
    )


def test_ask_endpoint_503_without_key(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "openai_api_key", "")
    resp = client.post("/api/nora/ask", json={"question": "hello"})
    assert resp.status_code == 503
    assert "BEACON_OPENAI_API_KEY" in resp.json()["detail"]


def test_conversations_endpoints(seeded, db, client):
    prop, chroma_dir = seeded
    result = nora.ask(
        db,
        "What does the CRM data show?",
        FakeLLM(),
        DeterministicEmbedder(),
        property_id=prop["id"],
        chroma_dir=chroma_dir,
    )
    conversations = client.get("/api/nora/conversations").json()
    assert len(conversations) == 1
    messages = client.get(
        f"/api/nora/conversations/{result['conversation_id']}"
    ).json()
    assert len(messages) == 2
    assert messages[1]["role"] == "assistant"
    assert messages[1]["citations"]


def test_conversations_filtered_by_property(seeded, db, client):
    prop, chroma_dir = seeded
    other = make_property(client, "The Marlowe")
    # One chat scoped to the seeded property, one portfolio-wide.
    nora.ask(
        db, "Property question?", FakeLLM(), DeterministicEmbedder(),
        property_id=prop["id"], chroma_dir=chroma_dir,
    )
    nora.ask(
        db, "Portfolio question?", FakeLLM(), DeterministicEmbedder(),
        property_id=None, chroma_dir=chroma_dir,
    )

    scoped = client.get(f"/api/nora/conversations?property_id={prop['id']}").json()
    assert len(scoped) == 1
    assert scoped[0]["property_id"] == prop["id"]

    none_for_other = client.get(
        f"/api/nora/conversations?property_id={other['id']}"
    ).json()
    assert none_for_other == []

    portfolio = client.get("/api/nora/conversations?scope=portfolio").json()
    assert len(portfolio) == 1
    assert portfolio[0]["property_id"] is None

    assert len(client.get("/api/nora/conversations").json()) == 2


def test_delete_conversation_removes_messages(seeded, db, client):
    prop, chroma_dir = seeded
    result = nora.ask(
        db, "Delete me?", FakeLLM(), DeterministicEmbedder(),
        property_id=prop["id"], chroma_dir=chroma_dir,
    )
    cid = result["conversation_id"]
    assert db.query(NoraMessage).filter_by(conversation_id=cid).count() == 2

    resp = client.delete(f"/api/nora/conversations/{cid}")
    assert resp.status_code == 204
    assert client.get("/api/nora/conversations").json() == []
    assert db.query(NoraMessage).filter_by(conversation_id=cid).count() == 0
    assert client.get(f"/api/nora/conversations/{cid}").status_code == 404


def test_delete_unknown_conversation_404(client):
    assert client.delete("/api/nora/conversations/9999").status_code == 404
