"""Phase 19 (3): metrics, rollups, recommendation and sentiment rules, the
opportunity score, and the slice 3 endpoints. Every metric carries its
formula, label and sample; below the minimum sample the value is null;
Share of Voice from observations matches the Phase 18 report exactly;
rollups are incremental and idempotent."""

from datetime import date, datetime, timedelta, timezone

from app.connectors.base import AIVisibilityQueryProvider
from app.models import (
    AIClusterVisibilityDaily,
    AIPromptCluster,
    AIPropertyObservation,
    AIVisibilityDaily,
    AppState,
    Competitor,
    GSCPerformanceDaily,
    Job,
    Property,
    SourceType,
    Upload,
    UploadStatus,
)
from app.services.ai_visibility.execution import run_query
from app.services.ai_visibility.providers import read_queries
from app.services.observatory.assignments import assign
from app.services.observatory.markets import assign_property_market
from app.services.observatory.metrics import METRIC_DEFINITIONS, metrics_for_window, prompt_coverage
from app.services.observatory.opportunity_score import prompt_opportunity_score
from app.services.observatory.prompt_library import PromptDraft, upsert_prompt
from app.services.observatory.recommendation import classify_recommendation
from app.services.observatory.rollups import WATERMARK_KEY, rebuild_rollups, update_property_rollups
from app.services.observatory.sentiment import mention_sentiment
from app.services.reporting_share_of_voice import build_sov_report

NOW = (datetime.now(timezone.utc) - timedelta(days=2)).replace(hour=12, minute=0, second=0, microsecond=0)
TODAY = datetime.now(timezone.utc).date()


class FR(AIVisibilityQueryProvider):
    name = "fake"

    def __init__(self, response):
        self.response = response

    def execute_query(self, prompt, platform):
        return self.response

    def get_queries(self, db, property_id):
        return read_queries(db, property_id)


def _prop(db, name="Metric Manor"):
    p = Property(name=name, slug=name.lower().replace(" ", "-"), city="Parker", state="CO",
                 website_url="https://www.metricmanor.com")
    db.add(p)
    db.commit()
    assign_property_market(db, p)
    p.domain = "metricmanor.com"
    db.add(Competitor(property_id=p.id, name="Rival Row", domain="https://rivalrow.com"))
    db.commit()
    return p


ANSWERS = [
    "Metric Manor is a top choice. Rival Row is fine too. https://www.metricmanor.com/a",
    "Consider Rival Row for parking. https://rivalrow.com/x",
    "Metric Manor has a pool and Rival Row has a gym.",
    "Nothing specific comes to mind for Parker.",
]


def _seed(db, p):
    for i, text in enumerate(ANSWERS):
        run_query(db, p.id, f"Prompt {i} Parker?", "chatgpt", provider=FR(text), now=NOW + timedelta(minutes=i))


def test_metrics_formulas_counts_and_labels(db):
    p = _prop(db)
    _seed(db, p)
    m = metrics_for_window(db, p.id, TODAY - timedelta(days=29), TODAY)
    assert m["counts"]["eligible_count"] == 4
    assert (m["ai_visibility"]["numerator"], m["ai_visibility"]["denominator"]) == (2, 4)
    assert m["ai_visibility"]["value"] == 0.5 and m["ai_visibility"]["data_label"] == "MEASURED"
    assert (m["citation_rate"]["numerator"], m["citation_rate"]["value"]) == (1, 0.25)
    assert m["recommendation_rate"]["data_label"] == "MODELED"
    # Competitor wins: responses 2 (Rival only) -> 1 of 4.
    assert m["competitor_win_rate"]["numerator"] == 1
    # Citation share: 1 owned vs 1 competitor citation.
    assert m["citation_share"]["value"] == 0.5
    for d in METRIC_DEFINITIONS.values():
        assert "—" not in d["formula"] and "—" not in (d.get("note") or "")


def test_share_of_voice_matches_phase18_report(db):
    p = _prop(db)
    _seed(db, p)
    m = metrics_for_window(db, p.id, TODAY - timedelta(days=29), TODAY)
    report = build_sov_report(db, p.id, days=30, today=TODAY)
    assert m["share_of_voice"]["value"] == report["overview"]["share_of_voice"]
    assert m["share_of_voice"]["numerator"] == report["overview"]["property_mentions"]
    assert m["share_of_voice"]["denominator"] == report["overview"]["total_mentions"]


def test_insufficient_sample_is_null_not_zero(db):
    p = _prop(db)
    run_query(db, p.id, "One prompt?", "chatgpt", provider=FR("Nothing here."), now=NOW)
    m = metrics_for_window(db, p.id, TODAY - timedelta(days=29), TODAY)
    assert m["ai_visibility"]["value"] is None and m["ai_visibility"]["state"] == "insufficient_sample"
    assert m["share_of_voice"]["value"] is None


def test_rollups_incremental_idempotent_with_watermark(db):
    p = _prop(db)
    _seed(db, p)
    assert db.query(AIPropertyObservation).filter_by(rolled_up=False).count() == 0  # rolled inline
    rows = db.query(AIVisibilityDaily).filter_by(property_id=p.id).all()
    assert {r.platform for r in rows} == {"all", "chatgpt"}
    all_row = next(r for r in rows if r.platform == "all")
    assert all_row.eligible_count == 4 and all_row.mentioned_count == 2
    again = update_property_rollups(db)
    assert again["keys"] == 0
    full = rebuild_rollups(db)
    assert full["keys"] == 1
    assert db.query(AIVisibilityDaily).filter_by(property_id=p.id).count() == 2  # no duplicates
    state = db.get(AppState, WATERMARK_KEY)
    assert state.value["observation_id"] == db.query(AIPropertyObservation).count()


def test_prompt_coverage_uses_priority_clusters(db):
    p = _prop(db)
    hi = AIPromptCluster(property_id=p.id, scope="brand", label="hi", importance=5)
    lo = AIPromptCluster(property_id=p.id, scope="brand", label="lo", importance=2)
    db.add_all([hi, lo])
    db.flush()
    assign(db, cluster_id=hi.id, property_id=p.id)
    assign(db, cluster_id=lo.id, property_id=p.id)
    db.commit()
    cov = prompt_coverage(db, p.id, TODAY - timedelta(days=29), TODAY)
    assert (cov["numerator"], cov["denominator"], cov["value"]) == (0, 1, 0.0)
    db.add(AIClusterVisibilityDaily(day=NOW.date(), property_id=p.id, cluster_id=hi.id, eligible_count=2,
                                    mentioned_count=1, rollup_key="t1"))
    db.commit()
    cov = prompt_coverage(db, p.id, TODAY - timedelta(days=29), TODAY)
    assert cov["value"] == 1.0 and cov["covered_cluster_ids"] == [hi.id]


def test_recommendation_rules():
    text = "Alpha is fine. Beta and Gamma too. Delta I would not recommend."
    assert classify_recommendation(text, mentioned=False, mention_position=None, mention_rank=None)[0] is None
    assert classify_recommendation(text, mentioned=True, mention_position=0, mention_rank=1)[0] is True
    rec, method, rules = classify_recommendation(
        text, mentioned=True, mention_position=text.index("Delta"), mention_rank=4
    )
    assert rec is False and method == "rule_v1" and any("negated" in r for r in rules)
    long_text = ("filler " * 40) + "Zeta Place is a great option for families."
    assert classify_recommendation(long_text, mentioned=True,
                                   mention_position=long_text.index("Zeta"), mention_rank=5)[0] is True
    plain = ("filler " * 40) + "Zeta Place exists."
    assert classify_recommendation(plain, mentioned=True,
                                   mention_position=plain.index("Zeta"), mention_rank=5)[0] is False


def test_mention_sentiment_is_windowed_and_neutral_by_default():
    label, score, excerpt = mention_sentiment("Zeta Place is clean and friendly.", 0, ["Zeta Place"])
    assert label == "positive" and score == 1.0 and "Zeta Place" in excerpt
    assert mention_sentiment("Zeta Place exists.", 0, ["Zeta Place"])[0] == "neutral"
    assert mention_sentiment("anything", None, ["Zeta"])[0] == "neutral"


def test_opportunity_score_is_modeled_and_redistributes_unavailable(db):
    p = _prop(db)
    c = AIPromptCluster(property_id=p.id, scope="feature", label="pools", topic_key="pool", importance=4)
    db.add(c)
    db.flush()
    db.add(AIClusterVisibilityDaily(day=NOW.date(), property_id=p.id, cluster_id=c.id, eligible_count=4,
                                    mentioned_count=1, competitor_win_count=2, rollup_key="o1"))
    db.commit()
    out = prompt_opportunity_score(db, p.id, c.id, today=TODAY)
    assert out["data_label"] == "MODELED" and 0 <= out["score"] <= 100
    assert out["contributors"]["search_demand"]["available"] is False
    assert out["contributors"]["momentum"]["available"] is False
    assert set(out["effective_weights"]) == {"competitor_presence", "visibility_gap", "topic_importance"}
    assert abs(sum(out["effective_weights"].values()) - 1) < 0.001
    assert "not prompt search volume" in out["explanation"]

    up = Upload(source_type=SourceType.GSC, property_id=p.id, filename="gsc.csv", status=UploadStatus.PROCESSED)
    db.add(up)
    db.flush()
    db.add(GSCPerformanceDaily(property_id=p.id, upload_id=up.id, date=NOW.date(),
                               query="parker apartments with pool", clicks=1, impressions=50, ctr=0.02, position=4.0))
    db.add(GSCPerformanceDaily(property_id=p.id, upload_id=up.id, date=NOW.date(),
                               query="parker apartments", clicks=1, impressions=50, ctr=0.02, position=4.0))
    db.commit()
    with_gsc = prompt_opportunity_score(db, p.id, c.id, today=TODAY)
    assert with_gsc["contributors"]["search_demand"]["value"] == 0.5
    tweaked = prompt_opportunity_score(db, p.id, c.id, today=TODAY, weight_overrides={"topic_importance": 0})
    assert tweaked["weights"]["topic_importance"] == 0


def test_overview_trends_sources_citations_endpoints(client, db):
    p = _prop(db)
    _seed(db, p)
    ov = client.get(f"/api/ai-observatory/overview?property_id={p.id}&days=30").json()
    assert ov["metrics"]["ai_visibility"]["value"] == 0.5
    assert ov["metrics"]["ai_visibility"]["comparison"]["previous"] is None
    assert ov["sample"]["eligible_responses"] == 4
    assert "prompt_coverage" in ov["metrics"]

    tr = client.get(f"/api/ai-observatory/trends?property_id={p.id}&metric=ai_visibility&days=7").json()
    assert tr["current"]["value"] == 0.5 and len(tr["series"]) == 1
    assert client.get(f"/api/ai-observatory/trends?property_id={p.id}&metric=bogus").status_code == 422

    src = client.get(f"/api/ai-observatory/sources?property_id={p.id}").json()
    assert src["total_citations"] == 2
    assert {d["domain"] for d in src["domains"]} == {"metricmanor.com", "rivalrow.com"}

    cit = client.get(f"/api/ai-observatory/citations?property_id={p.id}&limit=1").json()
    assert cit["total"] == 2 and len(cit["items"]) == 1 and cit["data_label"] == "OBSERVED"
    owned = client.get(f"/api/ai-observatory/citations?property_id={p.id}&domain=metricmanor.com").json()
    assert owned["items"][0]["owned"] is True

    obs = client.get(f"/api/ai-observatory/observations?property_id={p.id}").json()
    assert obs["total"] == 4

    meta = client.get("/api/ai-observatory/meta").json()
    assert meta["metrics"]["recommendation_rate"]["data_label"] == "MODELED"
    assert "—" not in str(meta)
    assert client.get("/api/ai-observatory/overview?property_id=9999").status_code == 404


def test_market_summary_and_run_enqueue(client, db):
    p = _prop(db)
    row, _ = upsert_prompt(db, PromptDraft(
        text="Best apartments in Parker, CO?", scope="market", topic_key="best_overall", intent="discovery",
        importance=5, funnel_stage="awareness", variant_group="g", is_representative=True,
        generated_from={}, market_id=p.market_id,
    ))
    db.commit()
    r = client.post(f"/api/ai-observatory/prompts/{row.id}/run")
    assert r.status_code == 200 and r.json()["created"] is True
    again = client.post(f"/api/ai-observatory/prompts/{row.id}/run").json()
    assert again["created"] is False and again["job_id"] == r.json()["job_id"]
    assert db.query(Job).filter_by(job_type="execute_market_run").count() == 1

    summary = client.get(f"/api/ai-observatory/markets/{p.market_id}/summary").json()
    assert [x["property_id"] for x in summary["leaderboard"]] == [p.id]
    assert "not consumer impressions" in summary["note"]
