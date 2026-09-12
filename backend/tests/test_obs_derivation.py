"""Phase 19 (3): shared market scoring. One market run -> one provider call,
one stored response, one derived observation per eligible property;
derivation is idempotent; eligibility follows cluster subscriptions;
market runs are charged to the organization budget; backfill derives
history without re-running any provider; property delete removes the
property's derived rows."""

from datetime import datetime, timedelta, timezone

import pytest

from app.connectors.base import AIVisibilityQueryProvider
from app.models import (
    AIBudget,
    AIPromptCluster,
    AIPropertyObservation,
    AIRun,
    AIVisibilityQuery,
    Competitor,
    Mention,
    Property,
)
from app.services.ai_visibility.execution import RateLimitExceeded, run_query
from app.services.ai_visibility.providers import read_queries
from app.services.observatory.assignments import assign
from app.services.observatory.budgets import period_key
from app.services.observatory.derivation import backfill_observations, rederive_response
from app.services.observatory.markets import assign_property_market
from app.services.observatory.observe import execute_market_prompt
from app.services.observatory.prompt_library import PromptDraft, upsert_prompt
from app.services.observatory.tenancy import default_organization_id

NOW = (datetime.now(timezone.utc) - timedelta(days=2)).replace(hour=12, minute=0, second=0, microsecond=0)

ANSWER = (
    "Top picks in Lone Tree: Alpha Flats is a top choice for commuters, and "
    "Rival Ridge is also popular. See https://www.alphaflats.com/tour and "
    "https://www.rivalridge.com for details, plus https://www.apartments.com/lone-tree-co."
)


class FR(AIVisibilityQueryProvider):
    name = "fake"

    def __init__(self, response):
        self.response = response
        self.calls = 0

    def execute_query(self, prompt, platform):
        self.calls += 1
        return self.response

    def get_queries(self, db, property_id):
        return read_queries(db, property_id)


def _prop(db, name, domain_url, city="Lone Tree", state="CO"):
    p = Property(name=name, slug=name.lower().replace(" ", "-"), city=city, state=state, website_url=domain_url)
    db.add(p)
    db.commit()
    assign_property_market(db, p)
    p.domain = domain_url.split("//")[1].removeprefix("www.").split("/")[0]
    db.commit()
    return p


def _market_prompt(db, market_id, text="Best apartments in Lone Tree, CO?"):
    row, _ = upsert_prompt(db, PromptDraft(
        text=text, scope="market", topic_key="best_overall", intent="discovery", importance=5,
        funnel_stage="awareness", variant_group="t:best", is_representative=True,
        generated_from={"template_id": "test"}, market_id=market_id,
        organization_id=default_organization_id(db),
    ))
    db.commit()
    return row


def _two_props(db):
    a = _prop(db, "Alpha Flats", "https://www.alphaflats.com")
    b = _prop(db, "Bravo Commons", "https://www.bravocommons.com")
    db.add(Competitor(property_id=b.id, name="Rival Ridge", domain="https://www.rivalridge.com"))
    db.commit()
    assert a.market_id == b.market_id
    return a, b


def test_one_market_run_scores_every_member_once(db):
    a, b = _two_props(db)
    prompt = _market_prompt(db, a.market_id)
    fake = FR(ANSWER)

    obs = execute_market_prompt(db, prompt.id, provider=fake, now=NOW)

    assert fake.calls == 1
    assert db.query(AIRun).count() == 1
    run = obs.run
    assert run.property_id is None and run.market_id == a.market_id and run.run_scope == "market"
    resp = obs.response
    assert resp.property_id is None and resp.market_id == a.market_id

    rows = {o.property_id: o for o in db.query(AIPropertyObservation).filter_by(response_id=resp.id)}
    assert set(rows) == {a.id, b.id}
    oa, ob = rows[a.id], rows[b.id]
    assert oa.eligibility_reason == "market_member"
    assert oa.mentioned and oa.mention_rank == 1 and oa.cited and oa.citation_count == 1
    assert oa.recommended is True and oa.recommendation_method == "rule_v1"
    assert oa.sentiment in {"positive", "neutral", "mixed"}
    assert oa.total_citation_count == 3
    # Bravo is absent but its tracked competitor is named and cited.
    assert not ob.mentioned and ob.recommended is None and ob.sentiment is None
    assert ob.competitor_mentioned_count == 1 and ob.competitor_cited_count == 1

    # Mentions stored once per entity for the shared answer.
    ments = db.query(Mention).filter_by(response_id=resp.id).all()
    assert {(m.entity_type, m.normalized_name) for m in ments} == {
        ("property", "Alpha Flats"), ("competitor", "Rival Ridge")
    }
    # Legacy per-property readers never see the market answer.
    assert db.query(AIVisibilityQuery).filter_by(property_id=a.id).count() == 0


def test_derivation_is_idempotent(db):
    a, b = _two_props(db)
    prompt = _market_prompt(db, a.market_id)
    obs = execute_market_prompt(db, prompt.id, provider=FR(ANSWER), now=NOW)
    before = [(o.property_id, o.mentioned, o.cited) for o in
              db.query(AIPropertyObservation).order_by(AIPropertyObservation.property_id)]
    rederive_response(db, obs.response.id)
    rederive_response(db, obs.response.id)
    after = [(o.property_id, o.mentioned, o.cited) for o in
             db.query(AIPropertyObservation).order_by(AIPropertyObservation.property_id)]
    assert before == after and len(after) == 2


def test_rederive_picks_up_new_competitor(db):
    a, b = _two_props(db)
    prompt = _market_prompt(db, a.market_id)
    obs = execute_market_prompt(db, prompt.id, provider=FR(ANSWER), now=NOW)
    oa = db.query(AIPropertyObservation).filter_by(response_id=obs.response.id, property_id=a.id).one()
    assert oa.competitor_mentioned_count == 0
    db.add(Competitor(property_id=a.id, name="Rival Ridge", domain="https://www.rivalridge.com"))
    db.commit()
    rederive_response(db, obs.response.id)
    oa = db.query(AIPropertyObservation).filter_by(response_id=obs.response.id, property_id=a.id).one()
    assert oa.competitor_mentioned_count == 1 and oa.competitor_cited_count == 1


def test_cluster_subscription_limits_eligibility(db):
    a, b = _two_props(db)
    prompt = _market_prompt(db, a.market_id)
    cluster = AIPromptCluster(market_id=a.market_id, scope="market", label="best", topic_key="best_overall",
                              importance=5, representative_prompt_id=prompt.id)
    db.add(cluster)
    db.flush()
    prompt.cluster_id = cluster.id
    assign(db, cluster_id=cluster.id, property_id=b.id)
    db.commit()

    obs = execute_market_prompt(db, prompt.id, provider=FR(ANSWER), now=NOW)
    rows = db.query(AIPropertyObservation).filter_by(response_id=obs.response.id).all()
    assert [(o.property_id, o.eligibility_reason, o.cluster_id) for o in rows] == [
        (b.id, "cluster_assignment", cluster.id)
    ]


def test_property_run_derives_one_observation(db):
    a, _ = _two_props(db)
    row = run_query(db, a.id, "Is Alpha Flats good?", "chatgpt", provider=FR(ANSWER), now=NOW)
    rows = db.query(AIPropertyObservation).filter_by(response_id=row.id).all()
    assert len(rows) == 1 and rows[0].property_id == a.id
    assert rows[0].eligibility_reason == "property_run" and rows[0].mentioned


def test_market_runs_charge_org_budget_and_stop_when_exhausted(db):
    a, _ = _two_props(db)
    prompt = _market_prompt(db, a.market_id)
    org_id = default_organization_id(db)
    execute_market_prompt(db, prompt.id, provider=FR(ANSWER), now=NOW)
    budget = db.query(AIBudget).filter_by(scope_type="org", scope_id=org_id, period=period_key()).one()
    assert budget.spent_runs == 1
    budget.allowance_runs = 1
    db.commit()
    with pytest.raises(RateLimitExceeded):
        execute_market_prompt(db, prompt.id, provider=FR(ANSWER), now=NOW)


def test_market_prompt_guards(db):
    a, _ = _two_props(db)
    brand, _ = upsert_prompt(db, PromptDraft(
        text="Is Alpha Flats good?", scope="brand", topic_key=None, intent="brand", importance=3,
        funnel_stage=None, variant_group="b", is_representative=True, generated_from={},
        property_id=a.id, market_id=a.market_id,
    ))
    db.commit()
    with pytest.raises(ValueError):
        execute_market_prompt(db, brand.id, provider=FR(ANSWER), now=NOW)
    prompt = _market_prompt(db, a.market_id)
    prompt.approved = False
    db.commit()
    with pytest.raises(ValueError):
        execute_market_prompt(db, prompt.id, provider=FR(ANSWER), now=NOW)


def test_backfill_derives_history_without_provider_calls(db):
    a, _ = _two_props(db)
    for i in range(3):
        run_query(db, a.id, f"Question {i} about Alpha Flats?", "chatgpt", provider=FR(ANSWER), now=NOW)
    # Simulate pre-Phase-18 history: no mentions, no observations.
    db.query(AIPropertyObservation).delete()
    db.query(Mention).delete()
    db.commit()
    out = backfill_observations(db)
    assert out["responses_total"] == 3 and out["responses_processed"] == 3
    rows = db.query(AIPropertyObservation).all()
    assert len(rows) == 3 and all(o.mentioned for o in rows)
    assert backfill_observations(db)["responses_total"] == 0


def test_property_delete_removes_derived_rows(client, db):
    a, b = _two_props(db)
    prompt = _market_prompt(db, a.market_id)
    obs = execute_market_prompt(db, prompt.id, provider=FR(ANSWER), now=NOW)
    a_id, b_id, response_id = a.id, b.id, obs.response.id
    r = client.delete(f"/api/properties/{a_id}")
    assert r.status_code == 200, r.text
    db.expire_all()
    remaining = db.query(AIPropertyObservation).filter_by(response_id=response_id).all()
    assert [o.property_id for o in remaining] == [b_id]
    assert not db.query(Mention).filter_by(entity_type="property", entity_id=a_id).count()
