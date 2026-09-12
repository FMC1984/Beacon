"""Phase 19 (5): competitor discovery (candidates only, confirm creates the
Competitor), AI fact claims (never false without a stored fact), alerts
(sample-gated, deduplicated, escalation), costs (UNAVAILABLE vs partial vs
full), the adaptive scheduler (config weights, budget, dry run, idempotent
enqueue), and admin AI Ops."""

from datetime import date, datetime, timedelta, timezone

from app.connectors.base import AIVisibilityQueryProvider
from app.models import (
    AIBudget,
    AIClaim,
    AIDiscoveredEntity,
    AIPromptCluster,
    AIRun,
    AIRunSchedule,
    AIScheduleDecision,
    AIVisibilityAlert,
    AIVisibilityDaily,
    Competitor,
    Job,
    Property,
    PropertyProfile,
)
from app.services.ai_visibility.execution import run_query
from app.services.ai_visibility.providers import read_queries
from app.services.observatory.alerts import detect_property_alerts, escalate
from app.services.observatory.assignments import assign
from app.services.observatory.budgets import period_key
from app.services.observatory.claims import extract_claims
from app.services.observatory.costs import cost_report
from app.services.observatory.discovery import candidates_for_property, decide, extract_candidate_names
from app.services.observatory.markets import assign_property_market
from app.services.observatory.observe import execute_market_prompt
from app.services.observatory.prompt_library import PromptDraft, upsert_prompt
from app.services.observatory.scheduler import config as sched_config
from app.services.observatory.scheduler import plan_runs, priority, sync_schedule
from app.services.observatory.tenancy import default_organization_id
from app.services.jobs.queue import utcnow

NOW = (datetime.now(timezone.utc) - timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
TODAY = datetime.now(timezone.utc).date()


class FR(AIVisibilityQueryProvider):
    name = "fake"

    def __init__(self, response):
        self.response = response

    def execute_query(self, prompt, platform):
        return self.response

    def get_queries(self, db, property_id):
        return read_queries(db, property_id)


def _prop(db, name="Alpha Flats", **kw):
    p = Property(name=name, slug=name.lower().replace(" ", "-"), city="Lone Tree", state="CO",
                 website_url=f"https://www.{name.lower().replace(' ', '')}.com", **kw)
    db.add(p)
    db.commit()
    assign_property_market(db, p)
    db.commit()
    return p


def _market_prompt(db, market_id, text="Best apartments in Lone Tree, CO?", importance=5):
    row, _ = upsert_prompt(db, PromptDraft(
        text=text, scope="market", topic_key="best_overall", intent="discovery", importance=importance,
        funnel_stage="awareness", variant_group=f"g:{text}", is_representative=True, generated_from={},
        market_id=market_id, organization_id=default_organization_id(db),
    ))
    cluster = AIPromptCluster(market_id=market_id, scope="market", label=text, topic_key="best_overall",
                              importance=importance, representative_prompt_id=row.id)
    db.add(cluster)
    db.flush()
    row.cluster_id = cluster.id
    db.commit()
    return row, cluster


# --- discovery ---------------------------------------------------------------

def test_candidate_extraction_filters_generic_and_known_names():
    text = ("**Alpha Flats** is great. The Retreat at Park Meadows has a pool. Luxury Apartments near "
            "Lone Tree vary; check Apartments.com. Sky Ridge Medical Center is close. Try Solana at RidgeGate.")
    names = [n for n, _ in extract_candidate_names(text)]
    assert names == ["Alpha Flats", "The Retreat at Park Meadows", "Solana at RidgeGate"]


def test_discovery_needs_repeat_evidence_and_confirm_creates_competitor(db):
    p = _prop(db)
    prompt, cluster = _market_prompt(db, p.market_id)
    assign(db, cluster_id=cluster.id, property_id=p.id)
    db.commit()
    answer = "Alpha Flats and Vista Ridge Apartments are both popular in Lone Tree."
    execute_market_prompt(db, prompt.id, provider=FR(answer), now=NOW)
    ent = db.query(AIDiscoveredEntity).filter_by(normalized_name="vista ridge apartments").one()
    assert ent.response_count == 1
    assert db.query(AIDiscoveredEntity).filter_by(normalized_name="alpha flats").count() == 0  # own name
    assert candidates_for_property(db, p.id) == []  # one answer is not enough

    execute_market_prompt(db, prompt.id, provider=FR(answer + " "), now=NOW + timedelta(minutes=5))
    cands = candidates_for_property(db, p.id)
    assert [c["name"] for c in cands] == ["Vista Ridge Apartments"]
    assert cands[0]["responses"] == 2 and cands[0]["confidence_label"] == "MODELED"
    assert db.query(Competitor).count() == 0  # never auto-tracked

    decide(db, ent.id, p.id, "confirmed", domain="https://vistaridge.com")
    comp = db.query(Competitor).filter_by(property_id=p.id).one()
    assert comp.name == "Vista Ridge Apartments" and comp.domain == "https://vistaridge.com"
    assert candidates_for_property(db, p.id) == []
    assert candidates_for_property(db, p.id, include_decided=True)[0]["decision"] == "confirmed"


def test_discovery_api_ignore_is_per_property(client, db):
    a = _prop(db, "Alpha Flats")
    b = _prop(db, "Bravo Commons")
    ent = AIDiscoveredEntity(market_id=a.market_id, normalized_name="vista ridge apartments",
                             display_name="Vista Ridge Apartments", response_count=3, mention_count=3,
                             evidence_response_ids=[], first_seen=NOW, last_seen=NOW)
    db.add(ent)
    db.commit()
    r = client.post(f"/api/ai-observatory/competitors/discovered/{ent.id}/decision",
                    json={"property_id": a.id, "decision": "ignored"})
    assert r.status_code == 200 and r.json()["competitor_id"] is None
    assert client.get(f"/api/ai-observatory/competitors/discovered?property_id={a.id}").json()["candidates"] == []
    other = client.get(f"/api/ai-observatory/competitors/discovered?property_id={b.id}").json()
    assert [c["name"] for c in other["candidates"]] == ["Vista Ridge Apartments"]
    bad = client.post(f"/api/ai-observatory/competitors/discovered/{ent.id}/decision",
                      json={"property_id": a.id, "decision": "maybe"})
    assert bad.status_code == 422


# --- claims ------------------------------------------------------------------

def test_claims_verify_against_recorded_facts_only(db):
    p = _prop(db, attributes={"pet_policy": "not_allowed", "amenities": ["Pool"], "rent_range": {"min": 1500, "max": 2100}})
    text = ("Alpha Flats is a pet-friendly community in Colorado with a pool and a rooftop dog park. "
            "Rent at Alpha Flats starts near $1,650. Alpha Flats does not have a gym. Alpha Flats is affordable housing.")
    by = {(c.claim_type, c.value): c for c in extract_claims(text, p, {"property_type": None}, set())}
    assert by[("pets", "pets allowed")].status == "conflict_detected"
    assert by[("amenity", "has pool")].status == "confirmed"
    # Not in the recorded list and no site content: unable to verify, never false.
    assert by[("amenity", "has dog park")].status == "unable_to_verify"
    assert by[("amenity", "no fitness center")].status == "unable_to_verify"
    assert by[("rent", "$1,650")].status == "likely_accurate"
    assert by[("state", "CO")].status == "confirmed"
    assert by[("property_type", "affordable")].status == "unable_to_verify"  # no Property Context type


def test_claims_persist_from_runs_and_raise_conflict_alert(client, db):
    p = _prop(db, attributes={"pet_policy": "not_allowed"})
    db.add(PropertyProfile(property_id=p.id, property_type="affordable"))
    db.commit()
    for i in range(2):
        run_query(db, p.id, f"Pets at Alpha Flats {i}?", "chatgpt",
                  provider=FR("Alpha Flats is pet-friendly and welcomes dogs."), now=NOW + timedelta(minutes=i))
    claim = db.query(AIClaim).filter_by(property_id=p.id, claim_type="pets").one()
    assert claim.occurrence_count == 2 and claim.verification_status == "conflict_detected"
    assert claim.severity == "high" and len(claim.response_ids) == 2

    body = client.get(f"/api/ai-observatory/claims?property_id={p.id}").json()
    assert body["counts"]["conflict_detected"] == 1 and body["claims"][0]["data_label"] == "OBSERVED"

    alerts = detect_property_alerts(db, p.id, today=TODAY)
    assert [a.alert_type for a in alerts] == ["claim_conflict"]
    assert detect_property_alerts(db, p.id, today=TODAY) == []  # deduplicated
    assert client.post(f"/api/ai-observatory/claims/{claim.id}/dismiss").json()["status"] == "dismissed"
    assert client.get(f"/api/ai-observatory/claims?property_id={p.id}").json()["claims"] == []


# --- alerts ------------------------------------------------------------------

def _daily(db, pid, day, eligible, mentioned, cited=0, comp_wins=0):
    for platform in ("all", "chatgpt"):
        db.add(AIVisibilityDaily(day=day, property_id=pid, platform=platform, eligible_count=eligible,
                                 mentioned_count=mentioned, property_mention_responses=mentioned,
                                 cited_count=cited, competitor_win_count=comp_wins, runs_count=eligible,
                                 rollup_key=f"{pid}:{platform}:{day.isoformat()}"))


def test_visibility_drop_alert_is_sample_gated_and_escalates(db):
    p = _prop(db)
    _daily(db, p.id, TODAY - timedelta(days=10), eligible=10, mentioned=8, cited=3)
    _daily(db, p.id, TODAY - timedelta(days=2), eligible=4, mentioned=1)
    db.commit()
    assert detect_property_alerts(db, p.id, today=TODAY) == []  # current window below 5 responses

    _daily(db, p.id, TODAY - timedelta(days=1), eligible=6, mentioned=1, comp_wins=6)
    db.commit()
    kinds = {a.alert_type: a for a in detect_property_alerts(db, p.id, today=TODAY)}
    assert set(kinds) == {"visibility_drop", "citation_lost", "competitor_surge"}
    drop = kinds["visibility_drop"]
    assert drop.metric_before == 0.8 and drop.metric_after == 0.2 and "not its cause" in drop.detail
    assert "—" not in drop.title + drop.detail

    prompt, cluster = _market_prompt(db, p.market_id)
    db.add(AIRunSchedule(prompt_id=prompt.id, cluster_id=cluster.id, market_id=p.market_id, platform="chatgpt",
                         tier="portfolio_market", cadence_days=7, repeat_count=1, schedule_key="x",
                         next_run_at=utcnow() + timedelta(days=5)))
    db.commit()
    assert escalate(db, drop) == 1
    row = db.query(AIRunSchedule).one()
    assert row.tier_override == "watchlist" and row.next_run_at <= utcnow()


# --- costs -------------------------------------------------------------------

def test_cost_report_labels_unpriced_and_partial(db):
    p = _prop(db)
    started = utcnow() - timedelta(hours=2)
    db.add(AIRun(property_id=p.id, platform="chatgpt", provider="openai", model="gpt-5-mini", run_scope="property",
                 status="success", started_at=started, token_input=1000, token_output=200, search_operations=1))
    db.commit()
    unpriced = cost_report(db, days=7)
    assert unpriced["total"]["cost"]["label"] == "UNAVAILABLE" and unpriced["total"]["cost"]["estimated_usd"] is None
    assert unpriced["total"]["tokens"]["input"] == 1000 and unpriced["total"]["tokens"]["label"] == "OBSERVED"

    db.add(AIRun(property_id=p.id, platform="chatgpt", provider="openai", model="gpt-5-mini", run_scope="property",
                 status="failed", started_at=started, estimated_cost=0.02))
    db.commit()
    partial = cost_report(db, days=7)["total"]["cost"]
    assert partial["coverage"] == "partial" and partial["estimated_usd"] == 0.02 and "lower bound" in partial["note"]
    assert cost_report(db, days=7)["total"]["by_status"] == {"failed": 1, "success": 1}


# --- scheduler ---------------------------------------------------------------

def test_scheduler_sync_plan_budget_and_idempotent_enqueue(client, db):
    p = _prop(db)
    hi, hi_cluster = _market_prompt(db, p.market_id, "Best apartments in Lone Tree, CO?", importance=5)
    lo, lo_cluster = _market_prompt(db, p.market_id, "Where to rent in Lone Tree, CO?", importance=2)
    orphan, _ = _market_prompt(db, p.market_id, "Unsubscribed prompt in Lone Tree, CO?", importance=5)
    assign(db, cluster_id=hi_cluster.id, property_id=p.id)
    assign(db, cluster_id=lo_cluster.id, property_id=p.id)
    db.commit()

    synced = sync_schedule(db)
    assert synced["created"] == 2  # the unsubscribed prompt gets no schedule row
    assert {r.prompt_id for r in db.query(AIRunSchedule)} == {hi.id, lo.id}

    now = utcnow()
    s_hi = db.query(AIRunSchedule).filter_by(prompt_id=hi.id).one()
    score, comps = priority(db, s_hi, now)
    assert set(comps) == set(sched_config()["priority_weights"]) and comps["staleness"] == 1.0

    dry = client.post("/api/ai-observatory/schedule/plan?dry_run=true").json()
    assert dry["dry_run"] and dry["selected"] == 2
    assert [d["prompt_id"] for d in dry["decisions"]] == [hi.id, lo.id]  # priority order
    assert db.query(Job).count() == 0 and db.query(AIRunSchedule).filter(AIRunSchedule.last_run_at.isnot(None)).count() == 0

    org = default_organization_id(db)
    budget = db.query(AIBudget).filter_by(scope_type="org", scope_id=org, period=period_key()).one()
    budget.allowance_runs = budget.spent_runs + 1
    db.commit()
    real = plan_runs(db, now=now, dry_run=False)
    assert [d["decision"] for d in real["decisions"]] == ["enqueued", "skipped_budget"]
    jobs = db.query(Job).filter_by(job_type="execute_market_run").all()
    assert len(jobs) == 1 and jobs[0].payload["prompt_id"] == hi.id
    assert db.query(AIScheduleDecision).filter_by(dry_run=False).count() == 2

    # Not due again until its cadence, and the queued run holds its budget:
    # re-planning enqueues nothing new.
    again = plan_runs(db, now=now + timedelta(minutes=1), dry_run=False)
    assert all(d["prompt_id"] != hi.id for d in again["decisions"])
    assert again["pending_runs_reserved"] == 1
    assert [d["decision"] for d in again["decisions"]] == ["skipped_budget"]
    assert db.query(Job).filter_by(job_type="execute_market_run").count() == 1

    listing = client.get(f"/api/ai-observatory/schedule?property_id={p.id}").json()
    assert listing["enabled"] is False and len(listing["rows"]) == 2


# --- endpoints ---------------------------------------------------------------

def test_alert_status_costs_and_admin_ops_endpoints(client, db):
    p = _prop(db)
    a = AIVisibilityAlert(property_id=p.id, alert_type="visibility_drop", severity="high", title="t", detail="d",
                          dedupe_key="k1")
    db.add(a)
    db.commit()
    assert client.get(f"/api/ai-observatory/alerts?property_id={p.id}").json()["alerts"][0]["id"] == a.id
    r = client.post(f"/api/ai-observatory/alerts/{a.id}/status", json={"status": "acknowledged"})
    assert r.json()["status"] == "acknowledged"
    assert client.post(f"/api/ai-observatory/alerts/{a.id}/status", json={"status": "gone"}).status_code == 422
    assert client.get(f"/api/ai-observatory/alerts?property_id={p.id}").json()["alerts"] == []

    assert client.get("/api/ai-observatory/costs?days=7").json()["total"]["runs"] == 0

    dead = Job(job_type="noop", idempotency_key="dead-1", status="dead", attempts=5, max_attempts=5,
               run_after=utcnow(), last_error="boom", error_class="provider_error")
    db.add(dead)
    db.commit()
    ops = client.get("/api/admin/ai-ops").json()
    assert ops["jobs"]["by_status"]["dead"] == 1 and ops["recent_failures"][0]["id"] == dead.id
    assert ops["scheduler_enabled"] is False and "budget" in ops
    assert client.post(f"/api/admin/jobs/{dead.id}/retry").json()["status"] == "queued"
    assert client.post(f"/api/admin/jobs/{dead.id}/retry").status_code == 409


def test_property_delete_removes_intelligence_rows(client, db):
    p = _prop(db, attributes={"pet_policy": "not_allowed"})
    run_query(db, p.id, "Pets at Alpha Flats?", "chatgpt", provider=FR("Alpha Flats is pet-friendly."), now=NOW)
    ent = AIDiscoveredEntity(market_id=p.market_id, normalized_name="x apartments", display_name="X Apartments",
                             response_count=2, evidence_response_ids=[])
    db.add(ent)
    db.add(AIVisibilityAlert(property_id=p.id, alert_type="claim_conflict", severity="high", title="t", detail="d",
                             dedupe_key="del-1"))
    db.commit()
    decide(db, ent.id, p.id, "ignored")
    pid = p.id
    assert db.query(AIClaim).filter_by(property_id=pid).count() == 1
    assert client.delete(f"/api/properties/{pid}").status_code == 200
    db.expire_all()
    from app.models import AIEntityDecision
    for model in (AIClaim, AIVisibilityAlert, AIEntityDecision):
        assert db.query(model).filter_by(property_id=pid).count() == 0
