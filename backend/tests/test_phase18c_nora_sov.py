"""Phase 18C: Nora's Share of Voice gate. Same posture as the correlation
gate - compute in code before generation, then template the system prompt -
so Nora can offer a Supported Diagnosis when a dominant topic contributor is
found, and is otherwise restricted to Observation/Hypothesis language,
never inventing a reason for a Share of Voice change."""

from datetime import datetime, timedelta, timezone

from app.connectors.base import AIVisibilityQueryProvider
from app.models import AITopic, Competitor, Property
from app.services import nora
from app.services.ai_visibility import run_query
from app.services.rag.embedder import DeterministicEmbedder
from app.services.rag.indexer import build_index
from app.services.reporting_share_of_voice import explain_sov_change


class FakeLLM:
    def __init__(self, reply="Grounded answer."):
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    def generate(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.reply


class FR(AIVisibilityQueryProvider):
    def __init__(self, response):
        self.response = response

    def execute_query(self, prompt, platform):
        return self.response

    def get_queries(self, db, property_id):
        return []


def _prop(db, name="Nora SoV Court"):
    p = Property(name=name, slug=name.lower().replace(" ", "-"))
    db.add(p)
    db.commit()
    return p


# --- question detection -------------------------------------------------------


def test_is_sov_question_detects_share_of_voice_language():
    assert nora.is_sov_question("Why did our AI Share of Voice decline?")
    assert nora.is_sov_question("Which competitor gained the most SOV?")
    assert nora.is_sov_question("Are we losing ground to competitors in ChatGPT?")


def test_is_sov_question_false_for_unrelated_question():
    assert not nora.is_sov_question("How much organic traffic did we get in June?")


# --- explain_sov_change: deterministic decomposition ---------------------------


def test_explain_sov_change_none_without_topics(db):
    p = _prop(db)
    comp = Competitor(property_id=p.id, name="Rival Co")
    db.add(comp)
    db.commit()

    now = datetime.now(timezone.utc)
    for i in range(3):
        run_query(
            db, p.id, "How is the property?", "chatgpt",
            provider=FR("Nora SoV Court is great."), now=now - timedelta(hours=i),
        )
    assert explain_sov_change(db, p.id, days=30, today=now.date()) is None


def test_explain_sov_change_finds_dominant_topic(db):
    p = _prop(db)
    comp = Competitor(property_id=p.id, name="Rival Co")
    db.add(comp)
    db.commit()
    topic = AITopic(property_id=p.id, topic_name="Pricing")
    db.add(topic)
    db.commit()

    from app.models import AIVisibilityPrompt

    prompt = AIVisibilityPrompt(
        property_id=p.id, prompt_text="What is the price?", platform="chatgpt",
        topic_id=topic.id,
    )
    db.add(prompt)
    db.commit()

    today = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
    prev_day = today - timedelta(days=45)

    # Previous period: property loses on this topic (0 of 3).
    for _ in range(3):
        run_query(
            db, p.id, "What is the price?", "chatgpt",
            provider=FR("Rival Co has the best pricing."), now=prev_day,
        )
    # Current period: property now wins consistently (3 of 3).
    for _ in range(3):
        run_query(
            db, p.id, "What is the price?", "chatgpt",
            provider=FR("Nora SoV Court has the best pricing."), now=today,
        )

    result = explain_sov_change(db, p.id, days=30, today=today.date())
    assert result is not None
    assert result["topic_id"] == topic.id
    assert result["point_change"] > 0
    assert result["aggregate_point_change"] > 0


# --- ask() gate wiring: system prompt branches, never guesses -----------------


def _index_property(db, prop, tmp_path):
    chroma_dir = str(tmp_path / "chroma")
    build_index(db, DeterministicEmbedder(), chroma_dir)
    return chroma_dir


def test_ask_sov_question_no_diagnosis_stays_observation_only(db, tmp_path):
    p = _prop(db)
    comp = Competitor(property_id=p.id, name="Rival Co")
    db.add(comp)
    db.commit()
    now = datetime.now(timezone.utc)
    for i in range(3):
        run_query(
            db, p.id, "How is the property?", "chatgpt",
            provider=FR("Nora SoV Court is great."), now=now - timedelta(hours=i),
        )
    chroma_dir = _index_property(db, p, tmp_path)

    llm = FakeLLM()
    result = nora.ask(
        db, "Why is our AI Share of Voice changing?", llm, DeterministicEmbedder(),
        property_id=p.id, chroma_dir=chroma_dir,
    )
    assert result["sov_gate"] == {"has_diagnosis": False}
    # No contributor found -> the model must be told not to guess a cause.
    if llm.calls:
        system_prompt = llm.calls[0][0]
        assert "not enough data" in system_prompt.lower() or "do not hypothesize" in system_prompt.lower()


def test_ask_non_sov_question_has_null_sov_gate(db, tmp_path):
    p = _prop(db)
    comp = Competitor(property_id=p.id, name="Rival Co")
    db.add(comp)
    db.commit()
    now = datetime.now(timezone.utc)
    run_query(
        db, p.id, "How is the property?", "chatgpt",
        provider=FR("Nora SoV Court is great."), now=now,
    )
    chroma_dir = _index_property(db, p, tmp_path)

    result = nora.ask(
        db, "What is our organic traffic this month?", FakeLLM(), DeterministicEmbedder(),
        property_id=p.id, chroma_dir=chroma_dir,
    )
    assert result["sov_gate"] is None
