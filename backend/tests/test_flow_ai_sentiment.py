"""AI Sentiment as a headline metric card on the Overview (flow: same counts
as the existing sentiment breakdown, never a second definition)."""

from datetime import datetime

from app.models import Property
from app.services.observatory.demo_seed import build_sample_portfolio
from app.services.observatory.metrics import METRIC_DEFINITIONS, _window, metric_from_counts, metrics_for_window
from app.services.observatory.rollups import rebuild_rollups

NOW = datetime(2026, 9, 10, 12, 0)
TODAY = NOW.date()


def _seeded(db, name="Maple Ridge Flats"):
    build_sample_portfolio(db, now=NOW, weeks=4)
    rebuild_rollups(db)
    return db.query(Property).filter_by(name=name).one()


def test_definition_is_labeled_modeled_with_a_stated_formula():
    d = METRIC_DEFINITIONS["ai_sentiment"]
    assert d["data_label"] == "MODELED" and "positive" in d["formula"] and "sentiment reading" in d["formula"]


def test_overview_ai_sentiment_reconciles_with_the_raw_counts(client, db):
    maple = _seeded(db)
    ov = client.get(f"/api/ai-observatory/overview?property_id={maple.id}&days=28&today={TODAY.isoformat()}").json()
    m = ov["metrics"]["ai_sentiment"]
    assert m["label"] == "AI Sentiment" and m["data_label"] == "MODELED"

    start, end = _window(28, TODAY)
    counts = metrics_for_window(db, maple.id, start, end)["counts"]
    total = counts["sentiment_pos"] + counts["sentiment_neu"] + counts["sentiment_neg"]
    assert m["numerator"] == counts["sentiment_pos"]
    assert m["denominator"] == total
    # Denominator is exactly the mention count: every mention gets a reading.
    assert m["denominator"] == counts["mentioned_count"]
    if total:
        assert m["value"] == round(counts["sentiment_pos"] / total, 4)
    # Matches the separate breakdown block, which the "How AI talks about the
    # property" panel reads: two views of one set of counts, never disagreeing.
    assert ov["sentiment"]["positive"] == m["numerator"]
    assert ov["sentiment"]["positive"] + ov["sentiment"]["neutral"] + ov["sentiment"]["negative"] == m["denominator"]


def test_ai_sentiment_card_is_clickable_and_opens_the_positive_mentions(client, db):
    maple = _seeded(db)
    ev = client.get(
        f"/api/ai-observatory/evidence?property_id={maple.id}&metric=ai_sentiment&days=28&today={TODAY.isoformat()}"
    ).json()
    ov = client.get(f"/api/ai-observatory/overview?property_id={maple.id}&days=28&today={TODAY.isoformat()}").json()
    assert ev["numerator"] == ov["metrics"]["ai_sentiment"]["numerator"]
    assert ev["description"] == "Mentions the semantic layer read as positive"


def test_below_sample_is_withheld_not_a_fabricated_number(db):
    p = Property(name="Quiet Court", slug="quiet-court")
    db.add(p)
    db.commit()
    m = metric_from_counts("ai_sentiment", 0, 0)
    assert m["value"] is None and m["state"] == "insufficient_sample"


def test_endpoint_404_for_unknown_property(client):
    assert client.get("/api/ai-observatory/overview?property_id=999999").status_code == 404
