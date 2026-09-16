"""Drilldown: every number walks back to rows. Query fanouts are grouped
per prompt and labeled OBSERVED, average position comes from stored
mention_rank, sentiment reasons are topic counts from the semantic layer,
and the generic evidence list returns exactly the observations a metric
counted. The Reports drilldown maps every summary card to its source rows
and refuses unknown cards with a reason rather than an empty list."""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import AIPropertyObservation, AIVisibilityQuery, Property
from app.services.observatory.demo_seed import build_sample_portfolio
from app.services.observatory.drilldown import (
    EVIDENCE_FILTERS,
    average_position,
    evidence,
    query_fanouts,
    sentiment_reasons,
)
from app.services.observatory.metrics import metrics_for_window
from app.services.reporting_drilldown import RESOLVERS, report_drilldown
from app.services.reporting_executive import build_executive_report

NOW = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0, tzinfo=None)
TODAY = NOW.date()


def _seeded(db):
    build_sample_portfolio(db, now=NOW, weeks=4)
    return db.query(Property).filter_by(name="Maple Ridge Flats").one()


def test_fanouts_group_provider_queries_per_prompt(db):
    p = _seeded(db)
    out = query_fanouts(db, p.id, days=30, today=TODAY)
    assert out["data_label"] == "OBSERVED" and "not searches people typed" in out["note"]
    assert out["responses"] > 0 and 0 < out["coverage"] <= 1
    assert out["prompts"], "sample runs record retrieval queries"
    top = out["prompts"][0]
    assert top["query_count"] == sum(v["count"] for v in top["variations"])
    assert abs(sum(v["share"] for v in top["variations"]) - 1) < 0.01
    assert top["avg_queries_per_execution"] == round(top["query_count"] / top["executions"], 2)


def test_fanouts_empty_window_is_a_state_not_a_zero(db):
    p = Property(name="Quiet Court", slug="quiet-court")
    db.add(p)
    db.commit()
    out = query_fanouts(db, p.id, days=30, today=TODAY)
    assert out["state"] == "empty" and out["coverage"] is None and out["prompts"] == []


def test_average_position_uses_stored_rank_and_is_sample_gated(db):
    p = _seeded(db)
    out = average_position(db, p.id, days=30, today=TODAY)
    cur = out["current"]
    ranks = [o.mention_rank for o in db.query(AIPropertyObservation).filter(
        AIPropertyObservation.property_id == p.id, AIPropertyObservation.mentioned.is_(True),
        AIPropertyObservation.mention_rank.isnot(None),
        AIPropertyObservation.observed_at >= NOW - timedelta(days=29)).all()]
    assert cur["ranked"] == len(ranks)
    assert cur["average_position"] == round(sum(ranks) / len(ranks), 2)
    assert cur["first_named"] == sum(1 for r in ranks if r == 1)
    assert sum(cur["distribution"].values()) == len(ranks)
    assert out["lower_is_better"] is True and out["state"] == "complete"

    q = Property(name="Thin Court", slug="thin-court")
    db.add(q)
    db.commit()
    thin = average_position(db, q.id, days=30, today=TODAY)
    assert thin["state"] == "insufficient_sample" and thin["current"]["average_position"] is None


def test_sentiment_reasons_are_topic_counts_with_quotes(db):
    p = _seeded(db)
    out = sentiment_reasons(db, p.id, days=30, today=TODAY)
    assert out["data_label"] == "MODELED" and "not a summary written by a model" in out["note"]
    assert out["mentions"] == sum(out["counts"].values())
    for r in out["positive_reasons"]:
        assert r["answers"] > 0 and r["label"] and len(r["quotes"]) <= 2
    if out["counts"]["positive"] + out["counts"]["negative"]:
        assert 0 <= out["positive_share"] <= 1
    else:
        assert out["positive_share"] is None


def test_evidence_matches_the_metric_it_explains(db):
    """The rows the drawer shows must be the rows the KPI counted."""
    p = _seeded(db)
    start = TODAY - timedelta(days=29)
    m = metrics_for_window(db, p.id, start, TODAY)
    for metric in ("ai_visibility", "citation_rate", "recommendation_rate", "competitor_win_rate"):
        e = evidence(db, p.id, metric, days=30, today=TODAY, limit=200)
        assert e["numerator"] == m[metric]["numerator"], metric
        assert e["denominator"] == m[metric]["denominator"], metric
        assert all(i["counts"] for i in e["items"])
    everything = evidence(db, p.id, "ai_visibility", days=30, today=TODAY, only_counting=False, limit=200)
    assert everything["total"] == everything["denominator"]
    assert any(not i["counts"] for i in everything["items"])
    first = everything["items"][0]
    assert first["answer"] and isinstance(first["citations"], list)
    with pytest.raises(ValueError):
        evidence(db, p.id, "made_up", days=30, today=TODAY)


def test_evidence_can_be_scoped_to_one_cluster(db):
    p = _seeded(db)
    cluster_id = db.query(AIPropertyObservation.cluster_id).filter(
        AIPropertyObservation.property_id == p.id, AIPropertyObservation.cluster_id.isnot(None)).first()[0]
    e = evidence(db, p.id, "all", days=30, today=TODAY, cluster_id=cluster_id, limit=200)
    assert e["denominator"] > 0
    assert e["denominator"] == db.query(AIPropertyObservation).filter(
        AIPropertyObservation.property_id == p.id, AIPropertyObservation.cluster_id == cluster_id,
        AIPropertyObservation.observed_at >= NOW - timedelta(days=29)).count()


def test_report_drilldown_totals_reconcile_with_the_cards(db):
    p = _seeded(db)
    exec_report = build_executive_report(db, p.id, days=30, today=TODAY)
    cards = {c["key"]: c for c in exec_report["cards"]}

    clicks = report_drilldown(db, p.id, "organic_clicks", days=30, today=TODAY)
    assert clicks["available"] and clicks["source"] == "Search Console"
    assert clicks["totals"]["clicks"] == cards["organic_clicks"]["value"]
    assert sum(i["clicks"] for i in clicks["items"]) == clicks["totals"]["clicks"]  # 8 queries fit in one page

    ai = report_drilldown(db, p.id, "ai_referral_sessions", days=30, today=TODAY)
    assert ai["totals"]["sessions"] == cards["ai_referral_sessions"]["value"]
    assert all(i["ai_platform"] for i in ai["items"])

    score = report_drilldown(db, p.id, "content_score", days=30, today=TODAY)
    assert score["totals"]["score"] == cards["content_score"]["value"]
    assert score["columns"][0] == "component"

    mention = report_drilldown(db, p.id, "ai_mention_rate", days=30, today=TODAY)
    assert mention["observatory_metric"] == "ai_visibility"
    assert mention["totals"]["counting"] <= mention["totals"]["eligible"]


def test_report_drilldown_refuses_unknown_cards_honestly(db, client):
    p = _seeded(db)
    out = report_drilldown(db, p.id, "some_future_card", days=30, today=TODAY)
    assert out["available"] is False and "no row-level drilldown yet" in out["reason"]
    with pytest.raises(ValueError):
        report_drilldown(db, 9999, "organic_clicks")

    listed = client.get("/api/reports/drilldown/cards").json()["cards"]
    assert set(listed) == set(RESOLVERS) and "organic_clicks" in listed
    body = client.get(f"/api/reports/drilldown?property_id={p.id}&card=top_city&days=30").json()
    assert body["available"] and body["group"] == "City" and body["items"][0]["region"] == "Colorado"
    assert client.get("/api/reports/drilldown?property_id=9999&card=organic_clicks").status_code == 404


def test_observatory_drilldown_endpoints(db, client):
    p = _seeded(db)
    for path, key in (("fanouts", "prompts"), ("position", "by_prompt"), ("sentiment", "positive_reasons")):
        body = client.get(f"/api/ai-observatory/{path}?property_id={p.id}&days=30").json()
        assert key in body
    ev = client.get(f"/api/ai-observatory/evidence?property_id={p.id}&metric=ai_visibility&limit=3").json()
    assert len(ev["items"]) == 3 and ev["showing"] == "counting"
    assert client.get(f"/api/ai-observatory/evidence?property_id={p.id}&metric=bogus").status_code == 422
    assert set(EVIDENCE_FILTERS) >= {"ai_visibility", "citation_rate", "share_of_voice", "all"}
    overview = client.get(f"/api/ai-observatory/overview?property_id={p.id}&days=30").json()
    assert overview["position"]["average"] is not None and overview["position"]["data_label"] == "MEASURED"
