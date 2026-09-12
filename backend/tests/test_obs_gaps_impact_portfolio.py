"""Phase 19 (6): content gaps from AI evidence (sample and evidence gated,
page coverage, Property Context gate, auto-resolve), the Opportunity Engine's
AI Observatory source with citations, AI + Search impact (association
wording, UNAVAILABLE steps), and portfolio averages and patterns."""

from datetime import date, datetime, timedelta, timezone

from app.models import (
    AIClusterVisibilityDaily,
    AIContentGap,
    AIPromptCluster,
    AIPropertyObservation,
    AIVisibilityQuery,
    Company,
    Competitor,
    GA4SessionsDaily,
    Property,
    PropertyContent,
    PropertyProfile,
    SourceType,
    Upload,
    UploadStatus,
)
from app.services.jobs.queue import utcnow
from app.services.observatory.assignments import assign
from app.services.observatory.content_gaps import evaluate_gaps
from app.services.observatory.impact import impact_summary
from app.services.observatory.markets import assign_property_market
from app.services.observatory.portfolio import portfolio_summary
from app.services.observatory.prompt_library import PromptDraft, upsert_prompt
from app.services.opportunity_engine import build_opportunities

TODAY = datetime.now(timezone.utc).date()
DAY = TODAY - timedelta(days=2)
CAUSAL = ("caused", "because of", "drove", "led to", "resulted in", "due to")


def _prop(db, name="Gap Gardens", company_id=None):
    p = Property(name=name, slug=name.lower().replace(" ", "-"), city="Parker", state="CO",
                 website_url=f"https://www.{name.lower().replace(' ', '')}.com", company_id=company_id)
    db.add(p)
    db.commit()
    assign_property_market(db, p)
    p.domain = f"{name.lower().replace(' ', '')}.com"
    db.commit()
    return p


def _cluster(db, p, topic="pets", importance=5, text="Which apartments in Parker, CO allow dogs?"):
    prompt, _ = upsert_prompt(db, PromptDraft(
        text=text, scope="feature", topic_key=topic, intent="discovery", importance=importance,
        funnel_stage="consideration", variant_group=f"g:{text}", is_representative=True, generated_from={},
        market_id=p.market_id,
    ))
    c = AIPromptCluster(market_id=p.market_id, scope="feature", label=text, topic_key=topic,
                        importance=importance, representative_prompt_id=prompt.id)
    db.add(c)
    db.flush()
    prompt.cluster_id = c.id
    assign(db, cluster_id=c.id, property_id=p.id)
    db.commit()
    return c


def _answers(db, p, cluster, n=4, mentioned=0, competitor=None, cite="bringfido.com"):
    """Seed n stored answers + observations + citations + a cluster rollup."""
    from app.models import AICitation

    for i in range(n):
        q = AIVisibilityQuery(property_id=None, market_id=p.market_id, platform="chatgpt", prompt_text=cluster.label,
                              raw_response_text="answer", executed_at=datetime.combine(DAY, datetime.min.time()) + timedelta(hours=i),
                              run_scope="feature", execution_status="success")
        db.add(q)
        db.flush()
        db.add(AICitation(response_id=q.id, url=f"https://{cite}/parker", normalized_url=f"https://{cite}/parker",
                          domain=cite, root_domain=cite, path="/parker", citation_order=0, source_type="directory",
                          capture_method="provider_annotation"))
        db.add(AIPropertyObservation(property_id=p.id, response_id=q.id, cluster_id=cluster.id, market_id=p.market_id,
                                     platform="chatgpt", observed_at=q.executed_at, eligible=True, mentioned=i < mentioned,
                                     competitor_mentioned_count=1 if competitor else 0,
                                     competitor_entity_ids=[competitor.id] if competitor else None,
                                     total_citation_count=1))
    wins = (n - mentioned) if competitor else 0
    db.add(AIClusterVisibilityDaily(day=DAY, property_id=p.id, cluster_id=cluster.id, eligible_count=n,
                                    mentioned_count=mentioned, competitor_win_count=wins,
                                    rollup_key=f"{p.id}:{cluster.id}:{DAY.isoformat()}"))
    db.commit()


def test_gap_detected_with_evidence_coverage_and_opportunity(db, client):
    p = _prop(db)
    comp = Competitor(property_id=p.id, name="Rival Row")
    db.add(comp)
    db.add(PropertyContent(property_id=p.id, page="faq", title="FAQ", body="We welcome dogs and cats. Pet friendly!"))
    db.commit()
    c = _cluster(db, p)
    _answers(db, p, c, n=4, mentioned=0, competitor=comp)

    out = evaluate_gaps(db, p.id, today=TODAY)
    assert out["gaps_open"] == 1
    g = db.query(AIContentGap).one()
    assert g.target_page == "faq" and g.page_exists
    assert "pet friendly" in g.covered_terms and "pets allowed" in g.missing_terms
    assert g.evidence["absent_responses"] == 4
    assert g.evidence["competitors_named"][0]["name"] == "Rival Row"
    assert g.evidence["cited_domains"][0]["domain"] == "bringfido.com"
    assert g.state == "Actionable" and g.impact == "High" and g.effort == "Low"
    assert "appeared in 0" in g.recommendation and "Rival Row" in g.recommendation
    assert not any(w in g.recommendation.lower() for w in CAUSAL) and "—" not in g.recommendation

    opps = build_opportunities(db, p.id, today=TODAY)
    ours = [o for o in opps["opportunities"] if o["source"] == "ai_observatory"]
    assert len(ours) == 1 and ours[0]["source_label"] == "AI Observatory"
    assert ours[0]["citations"][0]["source_ref"].startswith("ai_observatory: gap=")
    assert opps["by_source"]["AI Observatory"] == 1

    body = client.get(f"/api/ai-observatory/recommendations?property_id={p.id}").json()
    assert body["gaps"][0]["data_label"] == "MODELED"
    r = client.post(f"/api/ai-observatory/recommendations/{g.id}/status", json={"status": "dismissed"})
    assert r.json()["status"] == "dismissed"
    assert client.get(f"/api/ai-observatory/recommendations?property_id={p.id}").json()["gaps"] == []


def test_no_gap_without_sample_visibility_or_evidence(db):
    p = _prop(db)
    thin = _cluster(db, p, text="Q thin in Parker, CO?")
    _answers(db, p, thin, n=2, mentioned=0)  # below sample
    visible = _cluster(db, p, topic="pool", text="Q pool in Parker, CO?")
    _answers(db, p, visible, n=4, mentioned=3)  # visibility 75%
    assert evaluate_gaps(db, p.id, today=TODAY)["gaps_open"] == 0


def test_gap_without_content_is_insufficient_and_gate_applies(db):
    p = _prop(db)
    c = _cluster(db, p, topic="rent", text="How much is rent for apartments in Parker, CO?")
    _answers(db, p, c, n=3)
    evaluate_gaps(db, p.id, today=TODAY)
    g = db.query(AIContentGap).one()
    assert g.state == "Insufficient data" and "No site content" in g.gate_reason
    assert g.target_page == "floor_plans"

    db.add(PropertyContent(property_id=p.id, page="floor_plans", title="Floor Plans", body="Studios and one bedroom homes."))
    db.add(PropertyProfile(property_id=p.id, is_regulated=None))
    db.commit()
    evaluate_gaps(db, p.id, today=TODAY)
    db.refresh(g)
    # Rent is price messaging and regulatory status is unknown.
    assert g.state == "Requires confirmation"


def test_gap_auto_resolves_when_visibility_recovers(db):
    p = _prop(db)
    db.add(PropertyContent(property_id=p.id, page="faq", title="FAQ", body="Pets welcome."))
    db.commit()
    c = _cluster(db, p)
    _answers(db, p, c, n=4)
    evaluate_gaps(db, p.id, today=TODAY)
    row = db.query(AIClusterVisibilityDaily).one()
    row.mentioned_count = 4
    db.commit()
    out = evaluate_gaps(db, p.id, today=TODAY)
    assert out["auto_resolved"] == 1 and db.query(AIContentGap).one().status == "resolved"


def test_impact_is_association_only_with_unavailable_steps(db, client):
    p = _prop(db)
    ai_only = impact_summary(db, p.id, today=TODAY)
    assert ai_only["mode"] == "ai_only"
    labels = {s["step"]: s["label"] for s in ai_only["chain"]}
    assert labels["AI Overviews and generative-AI impressions"] == "UNAVAILABLE"
    assert labels["Sessions referred by AI platforms"] == "UNAVAILABLE"
    assert ai_only["alignment"] == "not_comparable"

    up = Upload(source_type=SourceType.GA4, property_id=p.id, filename="ga4.csv", status=UploadStatus.PROCESSED)
    db.add(up)
    db.flush()
    for d, sessions in ((TODAY - timedelta(days=40), 5), (TODAY - timedelta(days=3), 12)):
        db.add(GA4SessionsDaily(property_id=p.id, upload_id=up.id, date=d, session_source="chatgpt.com",
                                session_medium="referral", sessions=sessions, engaged_sessions=sessions,
                                total_users=sessions, key_events=1, is_ai_referral=True, ai_platform="chatgpt"))
    db.commit()
    body = client.get(f"/api/ai-observatory/impact?property_id={p.id}&days=30").json()
    assert body["mode"] == "ai_plus_search"
    stale = impact_summary(db, p.id, days=7, today=TODAY + timedelta(days=30))
    stale_step = next(s for s in stale["chain"] if s["step"] == "Sessions referred by AI platforms")
    assert stale_step["label"] == "UNAVAILABLE" and stale_step["current"] is None
    assert "No GA4 data in this period (latest" in stale_step["note"]
    step = next(s for s in body["chain"] if s["step"] == "Sessions referred by AI platforms")
    assert (step["current"], step["previous"], step["label"]) == (12, 5, "MEASURED")
    text = (body["note"] + body["alignment_text"]).lower()
    assert "not evidence that one caused the other" in text
    assert not any(w in body["alignment_text"].lower() for w in CAUSAL)


def test_portfolio_averages_need_two_sufficient_properties_and_find_shared_gaps(db, client):
    co = Company(name="Portfolio Co", slug="portfolio-co")
    db.add(co)
    db.commit()
    a = _prop(db, "Alpha Place", company_id=co.id)
    b = _prop(db, "Bravo Place", company_id=co.id)
    from app.models import AIVisibilityDaily

    db.add(AIVisibilityDaily(day=DAY, property_id=a.id, platform="all", eligible_count=4, mentioned_count=2,
                             property_mention_responses=2, rollup_key="pa"))
    db.commit()
    one = portfolio_summary(db, company_id=co.id, today=TODAY)
    assert one["averages"]["ai_visibility"]["value"] is None and one["averages"]["ai_visibility"]["properties"] == 1

    db.add(AIVisibilityDaily(day=DAY, property_id=b.id, platform="all", eligible_count=4, mentioned_count=4,
                             property_mention_responses=4, rollup_key="pb"))
    for prop in (a, b):
        c = _cluster(db, prop, text=f"Dog friendly apartments near {prop.name}, Parker, CO?")
        db.add(AIContentGap(property_id=prop.id, cluster_id=c.id, topic_key="pets", question="q", gap_key=f"k{prop.id}",
                            title="t", recommendation="r", state="Actionable", first_detected=utcnow(),
                            last_evaluated=utcnow()))
    db.commit()
    body = client.get(f"/api/ai-observatory/portfolio?company_id={co.id}").json()
    assert body["averages"]["ai_visibility"]["value"] == 0.75 and body["averages"]["ai_visibility"]["properties"] == 2
    assert body["shared_gaps"][0]["topic_key"] == "pets" and body["shared_gaps"][0]["properties"] == 2
    assert "not causes" in body["note"]
