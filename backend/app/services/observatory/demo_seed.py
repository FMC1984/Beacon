"""Sample Portfolio: a labeled, reversible demo dataset (Phase 19).

Builds a fictional organization, company, two markets and eight properties,
then drives the REAL observation pipeline with a scripted provider so every
Observatory surface fills the way it will once monitoring runs for real:
derived observations, daily rollups, metrics and trends, competitor
candidates, fact claims, alerts, content gaps and costs.

Honesty rules this obeys:
  - Nothing here is a measurement. Every property carries
    attributes["sample_data"] = True and the organization is flagged, so the
    UI can badge it; runs are recorded against the demo provider at zero cost.
  - Properties, competitors, cities and the AI answers are invented. No real
    community, client or competitor is named, so a screenshot cannot be
    mistaken for a finding about a real property.
  - It lives in its own organization with its own budget, so a real
    organization's data, spend and market runs are untouched, and
    `remove_sample_portfolio` deletes every row it created.
"""

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.connectors.base import (
    AIVisibilityQueryProvider,
    ProviderCitation,
    ProviderResult,
    ProviderUsage,
)
from app.models import (
    AIBudget,
    AICitation,
    AIClaim,
    AIClusterVisibilityDaily,
    AIContentGap,
    AIDiscoveredEntity,
    AIEntityDecision,
    AIMarketDaily,
    AIPromptAssignment,
    AIPromptCluster,
    AIPromptEmbedding,
    AIPropertyObservation,
    AIRun,
    AIRunSchedule,
    AISearchQuery,
    AIVisibilityAlert,
    AIVisibilityDaily,
    AIVisibilityPrompt,
    AIVisibilityQuery,
    Company,
    Competitor,
    Job,
    Market,
    Mention,
    Organization,
    Property,
    PropertyContent,
    PropertyProfile,
)
from app.services.jobs.queue import utcnow
from app.services.observatory.markets import ensure_market
from app.services.observatory.observability import log_event

SAMPLE_ORG_SLUG = "sample-portfolio"
SAMPLE_ORG_NAME = "Sample Portfolio (demo data)"
SAMPLE_COMPANY_NAME = "Sample Portfolio (demo data)"
SAMPLE_BUDGET_RUNS = 20000
WEEKS = 13
DIRECTORIES = ("apartments.com", "zillow.com", "rent.com", "apartmentlist.com")


@dataclass
class SampleProperty:
    name: str
    city: str
    state: str
    domain: str
    unit_count: int
    property_type: str = "multifamily_apartment"
    context_type: str | None = "conventional"
    pet_policy: str = "allowed"
    amenities: tuple[str, ...] = ("Pool", "Fitness Center")
    rent_min: int = 1400
    rent_max: int = 2200
    competitors: tuple[str, ...] = ()
    pages: tuple[str, ...] = ("homepage", "amenities", "floor_plans", "neighborhood", "faq")
    # 0..1 share of answers that name it, start and end of the window.
    visibility_start: float = 0.5
    visibility_end: float = 0.5
    # Progress (0..1) at which the share starts moving from start to end;
    # 0 = a steady slope across the window, 0.75 = a late cliff.
    cliff_at: float = 0.0
    cited: bool = True
    claims: tuple[str, ...] = field(default_factory=tuple)


LAKEMONT = ("Lakemont", "CO")
HARBOR_BEND = ("Harbor Bend", "TX")

SAMPLE_PROPERTIES: tuple[SampleProperty, ...] = (
    SampleProperty(
        name="Maple Ridge Flats", city=LAKEMONT[0], state=LAKEMONT[1], domain="mapleridgeflats.example",
        unit_count=248, amenities=("Pool", "Fitness Center", "Dog Park", "Garage"),
        rent_min=1550, rent_max=2400, competitors=("Copper Creek Commons", "Silver Oak Flats"),
        visibility_start=0.35, visibility_end=0.72, claims=("pool", "rent"),
    ),
    SampleProperty(
        name="Stonebrook Commons", city=LAKEMONT[0], state=LAKEMONT[1], domain="stonebrookcommons.example",
        unit_count=180, pet_policy="not_allowed", amenities=("Fitness Center", "Clubhouse"),
        rent_min=1350, rent_max=1950, competitors=("Copper Creek Commons", "Maple Ridge Flats"),
        visibility_start=0.55, visibility_end=0.12, cliff_at=0.9, cited=False, claims=("pets",),
    ),
    SampleProperty(
        name="Aspen Trail Apartments", city=LAKEMONT[0], state=LAKEMONT[1], domain="aspentrailapts.example",
        unit_count=312, amenities=("Pool", "EV Charging", "Washer and Dryer"),
        rent_min=1700, rent_max=2600, context_type="luxury", competitors=("Silver Oak Flats",),
        visibility_start=0.4, visibility_end=0.5, claims=("pool",),
    ),
    SampleProperty(
        name="Lakemont Senior Residences", city=LAKEMONT[0], state=LAKEMONT[1], domain="lakemontsenior.example",
        unit_count=96, context_type="senior", amenities=("Clubhouse", "Fitness Center"),
        rent_min=1200, rent_max=1750, competitors=("Brightwater Residences",),
        visibility_start=0.25, visibility_end=0.3, pages=("homepage", "amenities"),
    ),
    SampleProperty(
        name="Bayside Lofts", city=HARBOR_BEND[0], state=HARBOR_BEND[1], domain="baysidelofts.example",
        unit_count=220, amenities=("Pool", "Garage", "Dog Park"), rent_min=1500, rent_max=2300,
        competitors=("Tideline Apartments", "Harborview Flats"),
        visibility_start=0.6, visibility_end=0.66, claims=("pool", "rent"),
    ),
    SampleProperty(
        name="Harbor Bend Crossing", city=HARBOR_BEND[0], state=HARBOR_BEND[1], domain="harborbendcrossing.example",
        unit_count=164, context_type="affordable", amenities=("Clubhouse",), rent_min=950, rent_max=1400,
        competitors=("Tideline Apartments",), visibility_start=0.3, visibility_end=0.34,
        pages=("homepage", "floor_plans"),
    ),
    SampleProperty(
        name="Willow Park Apartments", city=HARBOR_BEND[0], state=HARBOR_BEND[1], domain="willowparkapts.example",
        unit_count=276, amenities=("Pool", "Fitness Center", "Washer and Dryer"), rent_min=1450, rent_max=2100,
        competitors=("Harborview Flats", "Bayside Lofts"), visibility_start=0.5, visibility_end=0.2, cliff_at=0.9,
        claims=("pool",),
    ),
    SampleProperty(
        name="Sunset Landing", city=HARBOR_BEND[0], state=HARBOR_BEND[1], domain="sunsetlanding.example",
        unit_count=142, amenities=("Dog Park", "Garage"), rent_min=1300, rent_max=1850,
        competitors=("Tideline Apartments",), visibility_start=0.2, visibility_end=0.22, cited=False,
    ),
)

# Named in answers often enough to surface as a discovery candidate, tracked
# by nobody: exactly the case the Competitors tab is for.
UNTRACKED_NAMES = ("Granite Bay Apartments", "Lantern District Lofts")

MARKET_PROMPTS = (
    ("best_overall", "What are the best apartments in {city}, {state}?"),
    ("pets", "Which apartments in {city}, {state} are pet friendly?"),
    ("rent", "How much is rent for a two bedroom in {city}, {state}?"),
    ("pool", "Which apartment communities in {city}, {state} have a pool?"),
    ("affordable", "What affordable apartments are available in {city}, {state}?"),
)
BRAND_PROMPT = "Is {name} in {city}, {state} a good place to live?"

PAGE_BODIES = {
    "homepage": "{name} offers apartment homes in {city}, {state} with a welcoming community and easy access to everything nearby.",
    "amenities": "Community amenities at {name} include {amenities}. Residents enjoy thoughtful spaces throughout the community.",
    "floor_plans": "{name} offers studio, one bedroom and two bedroom floor plans with modern finishes and generous storage.",
    "neighborhood": "{name} sits close to parks, schools and shopping in {city}, with quick access to major commuting routes.",
    "faq": "Frequently asked questions about living at {name}, including the application process and move in details.",
}


class ScriptedSampleProvider(AIVisibilityQueryProvider):
    """Returns a scripted answer instead of calling a provider. Runs it
    produces are recorded as the demo provider at zero cost."""

    name = "demo"

    def __init__(self, script):
        self._script = script
        self.model = "demo"

    def execute(self, prompt: str, platform: str, *, model=None, location=None) -> ProviderResult:
        text, citations, queries = self._script(prompt, platform)
        return ProviderResult(
            text=text, provider=self.name, platform=platform, model="demo",
            citations=tuple(ProviderCitation(url=u, title=t, capture_method="demo") for u, t in citations),
            search_queries=tuple(queries),
            usage=ProviderUsage(input_tokens=len(prompt.split()) * 3, output_tokens=len(text.split())),
            search_operations=1, browsed=True, latency_ms=900,
            raw_payload={"sample_data": True, "note": "Scripted sample answer, not a provider call."},
        )

    def execute_query(self, prompt: str, platform: str) -> str:
        return self.execute(prompt, platform).text

    def get_queries(self, db: Session, property_id: int):
        from app.services.ai_visibility.providers import read_queries

        return read_queries(db, property_id)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _share(sample: SampleProperty, progress: float) -> float:
    if progress <= sample.cliff_at:
        return sample.visibility_start
    span = max(1.0 - sample.cliff_at, 1e-6)
    return _lerp(sample.visibility_start, sample.visibility_end, (progress - sample.cliff_at) / span)


class _Pacer:
    """Names a property in exactly its scripted share of answers (an
    accumulator, not a coin flip) so the trend a property is scripted to
    show is the trend the rollups report."""

    def __init__(self):
        self.credit: dict[tuple[str, str], float] = {}

    def take(self, key: tuple[str, str], share: float) -> bool:
        c = self.credit.get(key, 0.5) + min(share, 0.95)
        hit = c >= 1.0
        self.credit[key] = c - 1.0 if hit else c
        return hit


def _answer(rng: random.Random, pacer: _Pacer, market_props: list[tuple[SampleProperty, Property]], topic: str,
            city: str, state: str, progress: float) -> tuple[str, list[tuple[str, str]], list[str]]:
    """One scripted market answer: which communities it names, in what order,
    with claims and citations. Shares drift across the window so trends move."""
    named: list[tuple[SampleProperty, Property]] = []
    for sample, prop in market_props:
        share = _share(sample, progress)
        if topic == "pets" and sample.pet_policy == "not_allowed":
            share += 0.25  # answers get this one wrong, which the claim check catches
        if topic == "pool" and "Pool" not in sample.amenities:
            share *= 0.3
        if topic == "affordable" and sample.context_type != "affordable":
            share *= 0.5
        if pacer.take((sample.name, ""), share):
            named.append((sample, prop))
    rng.shuffle(named)
    competitors = sorted({c for sample, _ in market_props for c in sample.competitors})
    extras = [c for c in competitors if rng.random() < 0.5][:2]
    extras += [n for n in UNTRACKED_NAMES if rng.random() < 0.45][:1]

    lines = [f"Here are some apartment communities in {city}, {state} worth a look:"]
    citations: list[tuple[str, str]] = []
    for sample, _ in named:
        bits = []
        if topic == "pets":
            bits.append("pet friendly with a dog park" if sample.pet_policy == "allowed" or topic == "pets" else "")
        if topic == "pool" and "Pool" in sample.amenities:
            bits.append("has a resort style pool")
        if topic == "rent":
            bits.append(f"two bedrooms start around ${rng.randrange(sample.rent_min, sample.rent_max, 50):,}")
        if not bits:
            bits.append(f"{sample.unit_count} apartment homes near downtown {city}")
        lines.append(f"- **{sample.name}**: {', '.join(b for b in bits if b)}.")
        if sample.cited and rng.random() < 0.7:
            citations.append((f"https://www.{sample.domain}/", sample.name))
    for extra in extras:
        lines.append(f"- {extra} is another option renters mention in {city}.")
    for directory in rng.sample(DIRECTORIES, k=2):
        citations.append((f"https://www.{directory}/{city.lower().replace(' ', '-')}-{state.lower()}", directory))
    queries = [f"{topic.replace('_', ' ')} apartments {city} {state}".strip(), f"best apartments {city}"]
    return "\n".join(lines), citations, queries


def _brand_answer(rng: random.Random, sample: SampleProperty, progress: float) -> tuple[str, list[tuple[str, str]], list[str]]:
    lines = [f"{sample.name} is an apartment community in {sample.city}, {sample.state}."]
    if "pool" in sample.claims and "Pool" in sample.amenities:
        lines.append(f"{sample.name} has a pool and a fitness center on site.")
    if "pets" in sample.claims:
        # Deliberate mismatch with the recorded policy, so Accuracy has a conflict.
        lines.append(f"{sample.name} is pet friendly and welcomes dogs.")
    if "rent" in sample.claims:
        lines.append(f"Rent at {sample.name} starts near ${rng.randrange(sample.rent_min, sample.rent_max, 25):,}.")
    lines.append(f"Residents mention the location in {sample.city} and the management team.")
    citations = [(f"https://www.{sample.domain}/", sample.name)] if sample.cited else []
    citations.append((f"https://www.{rng.choice(DIRECTORIES)}/{sample.domain.split('.')[0]}", "listing"))
    return " ".join(lines), citations, [f"{sample.name} reviews", f"{sample.name} apartments"]


def sample_organization(db: Session) -> Organization | None:
    return db.query(Organization).filter_by(slug=SAMPLE_ORG_SLUG).one_or_none()


def sample_status(db: Session) -> dict:
    org = sample_organization(db)
    if org is None:
        return {"present": False, "properties": 0, "responses": 0}
    prop_ids = [p.id for p in _sample_properties(db, org.id)]
    runs = db.query(AIRun).filter_by(organization_id=org.id).count()
    return {
        "present": True, "organization_id": org.id, "properties": len(prop_ids), "runs": runs,
        "observations": db.query(AIPropertyObservation).filter_by(organization_id=org.id).count(),
        "created_at": org.created_at.isoformat() if org.created_at else None,
    }


def _sample_properties(db: Session, org_id: int) -> list[Property]:
    company_ids = [cid for (cid,) in db.query(Company.id).filter(Company.organization_id == org_id)]
    if not company_ids:
        return []
    return db.query(Property).filter(Property.company_id.in_(company_ids)).order_by(Property.id).all()


def build_sample_portfolio(db: Session, now: datetime | None = None, weeks: int = WEEKS) -> dict:
    """Create the sample portfolio and its history. Idempotent: if the sample
    organization already exists it is removed and rebuilt, so the demo is
    always the same."""
    now = now or utcnow()
    if sample_organization(db) is not None:
        remove_sample_portfolio(db)
    rng = random.Random(1984)
    pacer = _Pacer()

    org = Organization(name=SAMPLE_ORG_NAME, slug=SAMPLE_ORG_SLUG, is_active=True,
                       settings={"sample_data": True, "note": "Labeled demo portfolio; not real monitoring."})
    db.add(org)
    db.flush()
    company = Company(name=SAMPLE_COMPANY_NAME, slug="sample-portfolio-demo", organization_id=org.id)
    db.add(company)
    db.flush()
    db.add(AIBudget(scope_type="org", scope_id=org.id, period=now.strftime("%Y-%m"),
                    allowance_runs=SAMPLE_BUDGET_RUNS, spent_runs=0, spent_usd=0.0))

    created: list[tuple[SampleProperty, Property]] = []
    for s in SAMPLE_PROPERTIES:
        prop = Property(
            name=s.name, slug=s.name.lower().replace(" ", "-"), property_type=s.property_type,
            company_id=company.id, city=s.city, state=s.state, unit_count=s.unit_count,
            website_url=f"https://www.{s.domain}", domain=s.domain, is_active=True,
            attributes={"sample_data": True, "amenities": list(s.amenities), "pet_policy": s.pet_policy,
                        "rent_range": {"min": s.rent_min, "max": s.rent_max}},
            management_company=SAMPLE_COMPANY_NAME,
        )
        db.add(prop)
        db.flush()
        market = ensure_market(db, s.city, s.state)
        prop.market_id = market.id
        if s.context_type:
            db.add(PropertyProfile(property_id=prop.id, property_type=s.context_type,
                                   is_regulated=s.context_type == "affordable"))
        for page in s.pages:
            body = PAGE_BODIES[page].format(name=s.name, city=s.city, state=s.state,
                                            amenities=", ".join(s.amenities).lower())
            db.add(PropertyContent(property_id=prop.id, page=page, title=f"{s.name} {page.replace('_', ' ').title()}",
                                   body=body, source_url=f"https://www.{s.domain}/{page}", updated_at=now,
                                   topics=[], content_hash=None))
        for comp in s.competitors:
            db.add(Competitor(property_id=prop.id, name=comp,
                              domain=f"https://www.{comp.lower().replace(' ', '')}.example"))
        created.append((s, prop))
    db.commit()

    markets: dict[tuple[str, str], int] = {}
    for s, prop in created:
        markets[(s.city, s.state)] = prop.market_id

    # Prompts and clusters, built directly (no embedding calls for a demo).
    clusters: dict[tuple[int, str], AIPromptCluster] = {}
    for (city, state), market_id in markets.items():
        for topic, template in MARKET_PROMPTS:
            text = template.format(city=city, state=state)
            prompt = AIVisibilityPrompt(
                property_id=None, market_id=market_id, organization_id=org.id, prompt_text=text,
                platform="chatgpt", scope="market" if topic in ("best_overall", "rent", "affordable") else "feature",
                topic_key=topic, intent="discovery", importance=5 if topic == "best_overall" else 4,
                funnel_stage="awareness", approved=True, active=True, is_representative=True,
                variant_group=f"sample:{topic}", generation_method="sample", generated_from={"sample_data": True},
                cadence="weekly",
            )
            db.add(prompt)
            db.flush()
            cluster = AIPromptCluster(market_id=market_id, organization_id=org.id, scope=prompt.scope,
                                      label=text, topic_key=topic, intent="discovery",
                                      importance=prompt.importance, representative_prompt_id=prompt.id,
                                      variant_count=1, embedding_model="sample")
            db.add(cluster)
            db.flush()
            prompt.cluster_id = cluster.id
            clusters[(market_id, topic)] = cluster
    for s, prop in created:
        text = BRAND_PROMPT.format(name=s.name, city=s.city, state=s.state)
        brand = AIVisibilityPrompt(
            property_id=prop.id, market_id=prop.market_id, organization_id=org.id, prompt_text=text,
            platform="chatgpt", scope="brand", topic_key=None, intent="brand", importance=4,
            approved=True, active=True, is_representative=True, variant_group=f"sample:brand:{prop.id}",
            generation_method="sample", generated_from={"sample_data": True}, cadence="monthly",
        )
        db.add(brand)
        db.flush()
        cluster = AIPromptCluster(property_id=prop.id, market_id=prop.market_id, organization_id=org.id,
                                  scope="brand", label=text, importance=4, representative_prompt_id=brand.id,
                                  variant_count=1, embedding_model="sample")
        db.add(cluster)
        db.flush()
        brand.cluster_id = cluster.id
        db.add(AIPromptAssignment(organization_id=org.id, cluster_id=cluster.id, property_id=prop.id,
                                  assignment_key=f"c{cluster.id}|p|prop{prop.id}|mkt", tier="standard_property",
                                  active=True, source="sample"))
        for topic, _ in MARKET_PROMPTS:
            market_cluster = clusters[(prop.market_id, topic)]
            db.add(AIPromptAssignment(organization_id=org.id, cluster_id=market_cluster.id, property_id=prop.id,
                                      assignment_key=f"c{market_cluster.id}|p|prop{prop.id}|mkt",
                                      tier="portfolio_market", active=True, source="sample"))
    db.commit()

    from app.services.observatory.observe import execute_market_prompt, execute_observation

    runs = 0
    for week in range(weeks):
        when = now - timedelta(days=7 * (weeks - 1 - week), hours=3)
        progress = week / max(weeks - 1, 1)
        for (city, state), market_id in markets.items():
            market_props = [(s, p) for s, p in created if p.market_id == market_id]
            for topic, _ in MARKET_PROMPTS:
                cluster = clusters[(market_id, topic)]
                prompt_id = cluster.representative_prompt_id
                script = lambda _p, _plat, t=topic, c=city, st=state, mp=market_props, pr=progress: _answer(
                    rng, pacer, mp, t, c, st, pr
                )
                for repeat in range(2):
                    execute_market_prompt(db, prompt_id, provider=ScriptedSampleProvider(script),
                                          now=when + timedelta(hours=6 * repeat), repeat_index=repeat)
                    runs += 1
        if week % 4 == 0:  # brand prompts run monthly
            for s, prop in created:
                brand = db.query(AIVisibilityPrompt).filter_by(property_id=prop.id, scope="brand").first()
                script = lambda _p, _plat, sp=s, pr=progress: _brand_answer(rng, sp, pr)
                execute_observation(
                    db, property_id=prop.id, prompt_text=brand.prompt_text, platform="chatgpt",
                    run_scope="brand", prompt_id=brand.id, organization_id=org.id, market_id=prop.market_id,
                    provider=ScriptedSampleProvider(script), now=when,
                )
                runs += 1

    from app.services.observatory.alerts import detect_property_alerts
    from app.services.observatory.content_gaps import evaluate_gaps
    from app.services.observatory.rollups import update_market_rollups

    update_market_rollups(db, market_ids=list(markets.values()))
    gaps = alerts = 0
    today = now.date()
    for _s, prop in created:
        gaps += evaluate_gaps(db, prop.id, days=90, today=today)["gaps_open"]
        alerts += len(detect_property_alerts(db, prop.id, today=today))
    db.commit()

    status = sample_status(db)
    log_event("sample_portfolio.built", organization_id=org.id, runs=runs, gaps=gaps, alerts=alerts)
    return {**status, "runs_created": runs, "content_gaps": gaps, "alerts": alerts,
            "markets": [f"{c}, {s}" for c, s in markets],
            "note": "Sample data only. Every property is flagged sample_data and runs are recorded at zero cost."}


def remove_sample_portfolio(db: Session) -> dict:
    """Delete every row the sample portfolio created, newest dependency
    first. Markets are shared geography, so a sample market is removed only
    when no property is left in it."""
    org = sample_organization(db)
    if org is None:
        return {"removed": False, "reason": "No sample portfolio is present."}
    props = _sample_properties(db, org.id)
    prop_ids = [p.id for p in props]
    market_ids = {p.market_id for p in props if p.market_id}

    response_ids = [rid for (rid,) in db.query(AIVisibilityQuery.id).filter_by(organization_id=org.id)]
    if response_ids:
        for leaf in (AIPropertyObservation, Mention, AICitation, AISearchQuery):
            db.query(leaf).filter(leaf.response_id.in_(response_ids)).delete(synchronize_session=False)
    if prop_ids:
        for model in (AIPropertyObservation, AIVisibilityDaily, AIClusterVisibilityDaily, AIPromptAssignment,
                      AIClaim, AIContentGap, AIVisibilityAlert, AIRunSchedule, AIEntityDecision,
                      PropertyContent, PropertyProfile, Competitor):
            db.query(model).filter(model.property_id.in_(prop_ids)).delete(synchronize_session=False)
    prompt_ids = [pid for (pid,) in db.query(AIVisibilityPrompt.id).filter_by(organization_id=org.id)]
    if prompt_ids:
        db.query(AIPromptEmbedding).filter(AIPromptEmbedding.prompt_id.in_(prompt_ids)).delete(synchronize_session=False)
        db.query(AIRunSchedule).filter(AIRunSchedule.prompt_id.in_(prompt_ids)).delete(synchronize_session=False)
    for model in (AIVisibilityQuery, AIRun, AIVisibilityPrompt, AIPromptCluster, AIPromptAssignment, Job):
        db.query(model).filter(model.organization_id == org.id).delete(synchronize_session=False)
    if market_ids:
        db.query(AIDiscoveredEntity).filter(AIDiscoveredEntity.market_id.in_(market_ids)).delete(synchronize_session=False)
        db.query(AIMarketDaily).filter(AIMarketDaily.market_id.in_(market_ids)).delete(synchronize_session=False)
    db.query(AIBudget).filter_by(scope_type="org", scope_id=org.id).delete(synchronize_session=False)
    for prop in props:
        db.delete(prop)
    db.query(Company).filter_by(organization_id=org.id).delete(synchronize_session=False)
    db.flush()
    for market_id in market_ids:
        if not db.query(Property.id).filter_by(market_id=market_id).first():
            db.query(Market).filter_by(id=market_id).delete(synchronize_session=False)
    db.delete(org)
    db.commit()
    log_event("sample_portfolio.removed", organization_id=org.id, properties=len(prop_ids))
    return {"removed": True, "properties": len(prop_ids), "responses": len(response_ids)}
