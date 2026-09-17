"""Nora reads the Observatory (flow P1): a labeled summary chunk per property
and a compute-then-template gate for "why did AI visibility change"."""

from datetime import date, datetime, timedelta, timezone

from app.models import AIClusterVisibilityDaily, AIVisibilityDaily, Property
from app.services import nora
from app.services.observatory.demo_seed import build_sample_portfolio
from app.services.observatory.metrics import _window, metrics_for_window
from app.services.observatory.rollups import rebuild_rollups
from app.services.observatory.summary import explain_visibility_change, observatory_summary_text
from app.services.rag.chunker import build_chunks
from app.services.rag.embedder import DeterministicEmbedder
from app.services.rag.indexer import build_index
from app.services.reporting import previous_window

NOW = datetime(2026, 9, 10, 12, 0)
TODAY = NOW.date()


class FakeLLM:
    def __init__(self, reply="Grounded answer."):
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    def generate(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.reply


def _seeded(db):
    build_sample_portfolio(db, now=NOW, weeks=4)
    rebuild_rollups(db)
    return db.query(Property).filter_by(name="Maple Ridge Flats").one()


def test_summary_none_without_monitoring(db):
    p = Property(name="Quiet Court", slug="quiet-court")
    db.add(p)
    db.commit()
    assert observatory_summary_text(db, p.id, today=TODAY) is None


def test_summary_carries_the_overview_numbers_and_labels(db):
    maple = _seeded(db)
    text = observatory_summary_text(db, maple.id, days=28, today=TODAY)
    assert text is not None
    start, end = _window(28, TODAY)
    m = metrics_for_window(db, maple.id, start, end)["ai_visibility"]
    assert f"({m['numerator']} of {m['denominator']})" in text
    assert "AI Visibility" in text and "MEASURED" in text and "OBSERVED" in text
    assert "never reports AI search volume" in text
    assert "—" not in text


def test_chunk_built_and_scoped(db):
    maple = _seeded(db)
    other = Property(name="Unmonitored Court", slug="unmonitored-court")
    db.add(other)
    db.commit()
    chunks = build_chunks(db, sources=["ai_observatory"])
    by_prop = {c.property_id: c for c in chunks}
    assert maple.id in by_prop and other.id not in by_prop
    assert by_prop[maple.id].chroma_id == f"ai_observatory-p{maple.id}"
    assert by_prop[maple.id].source == "ai_observatory"


def test_visibility_question_detection():
    assert nora.is_visibility_question("Why did our AI visibility drop last month?")
    assert nora.is_visibility_question("What is our citation rate?")
    assert not nora.is_visibility_question("How many leads came from Zillow?")


def _rollup(db, pid, day, eligible, mentioned, cluster_rows):
    db.add(AIVisibilityDaily(day=day, property_id=pid, platform="all", eligible_count=eligible, mentioned_count=mentioned,
                             property_mention_responses=mentioned, rollup_key=f"{pid}:all:{day}"))
    for cid, e, m in cluster_rows:
        db.add(AIClusterVisibilityDaily(day=day, property_id=pid, cluster_id=cid, eligible_count=e, mentioned_count=m,
                                        rollup_key=f"{pid}:{cid}:{day}"))


def test_explain_visibility_change_finds_the_dominant_question(db):
    p = Property(name="Diag Court", slug="diag-court")
    db.add(p)
    db.commit()
    start, end = _window(30, TODAY)
    prev_start, _ = previous_window(start, end)
    # Previous period: 10 answers per day-bucket, cluster 1 always names it, cluster 2 half.
    _rollup(db, p.id, prev_start, 10, 8, [(1, 5, 5), (2, 5, 3)])
    # Current period: cluster 1 collapses (5 of 5 -> 0 of 5), cluster 2 unchanged.
    _rollup(db, p.id, start, 10, 3, [(1, 5, 0), (2, 5, 3)])
    db.commit()
    out = explain_visibility_change(db, p.id, days=30, today=TODAY)
    assert out is not None and out["cluster_id"] == 1
    assert out["point_change"] < 0 and out["aggregate_point_change"] < 0
    assert out["prompt"] == "cluster 1"  # no cluster row: honest fallback label


def test_explain_visibility_change_none_when_aggregate_barely_moved(db):
    p = Property(name="Flat Court", slug="flat-court")
    db.add(p)
    db.commit()
    start, end = _window(30, TODAY)
    prev_start, _ = previous_window(start, end)
    _rollup(db, p.id, prev_start, 100, 50, [(1, 5, 5)])
    _rollup(db, p.id, start, 100, 51, [(1, 5, 0)])  # one cluster swung, aggregate moved 1 pt
    db.commit()
    assert explain_visibility_change(db, p.id, days=30, today=TODAY) is None


def test_ask_visibility_question_wires_the_gate(db, tmp_path):
    maple = _seeded(db)
    chroma_dir = str(tmp_path / "chroma")
    build_index(db, DeterministicEmbedder(), chroma_dir)
    llm = FakeLLM()
    result = nora.ask(db, "Why did our AI visibility change?", llm, DeterministicEmbedder(),
                      property_id=maple.id, chroma_dir=chroma_dir)
    assert result["visibility_gate"] is not None and "has_diagnosis" in result["visibility_gate"]
    assert result["sov_gate"] is None
    if llm.calls:
        system = llm.calls[0][0]
        assert "AI Visibility change" in system
        if not result["visibility_gate"]["has_diagnosis"]:
            assert "do not hypothesize" in system.lower()


def test_ask_unrelated_question_has_null_visibility_gate(db, tmp_path):
    maple = _seeded(db)
    chroma_dir = str(tmp_path / "chroma")
    build_index(db, DeterministicEmbedder(), chroma_dir)
    result = nora.ask(db, "How many reviews came in this month?", FakeLLM(), DeterministicEmbedder(),
                      property_id=maple.id, chroma_dir=chroma_dir)
    assert result["visibility_gate"] is None
