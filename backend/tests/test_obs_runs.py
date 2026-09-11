"""Phase 19 (1a): the run ledger. Every attempt is recorded (success, failed,
discarded) with whatever it cost; only successful responses become evidence
rows, so legacy readers of ai_visibility_queries are unchanged; citations,
retrieval queries and mentions are persisted alongside the response; the
query detail endpoint exposes all of it with data-integrity labels."""

from datetime import datetime, timezone

import pytest

from app.config import settings
from app.connectors.base import AIVisibilityQueryProvider, ProviderResult, ProviderUsage
from app.models import AICitation, AIRun, AISearchQuery, AIVisibilityQuery, Competitor, Mention, Property
from app.services.ai_visibility.execution import RateLimitExceeded, run_query
from app.services.ai_visibility.providers import BrowsingUnavailableError, DemoVisibilityProvider, read_queries
from app.services.observatory.observe import execute_observation


class FR(AIVisibilityQueryProvider):
    """Legacy-style fake: string only, so the base shim path is exercised."""

    name = "fake"

    def __init__(self, response):
        self.response = response

    def execute_query(self, prompt, platform):
        return self.response

    def get_queries(self, db, property_id):
        return read_queries(db, property_id)


class Exploding(FR):
    def execute_query(self, prompt, platform):
        raise RuntimeError("provider down")


class NonBrowsing(FR):
    def execute(self, prompt, platform, *, model=None, location=None):
        partial = ProviderResult(
            text="from memory", provider=self.name, platform=platform,
            usage=ProviderUsage(input_tokens=77, output_tokens=11), browsed=False,
        )
        raise BrowsingUnavailableError("no browse", result=partial)


def _prop(db, name="Ledger Court"):
    p = Property(
        name=name, slug=name.lower().replace(" ", "-"),
        website_url="https://www.ledgercourt.com",
    )
    db.add(p)
    db.commit()
    return p


NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def test_success_writes_run_evidence_citations_and_mentions(db):
    p = _prop(db)
    db.add(Competitor(property_id=p.id, name="Rival Co", domain="https://rival.com"))
    db.commit()

    row = run_query(
        db, p.id, "Is Ledger Court good?", "chatgpt",
        provider=FR("Ledger Court is great, see https://www.ledgercourt.com/tour and https://rival.com/x."),
        now=NOW,
    )
    run = db.get(AIRun, row.run_id)
    assert run is not None and run.status == "success"
    assert run.provider == "fake" and run.property_id == p.id and run.run_scope == "property"
    assert run.response_hash == row.response_hash and len(row.response_hash) == 64
    assert run.browsed is None  # the string provider cannot say
    assert run.estimated_cost is None and run.pricing_version  # UNAVAILABLE, versioned

    cites = db.query(AICitation).filter_by(response_id=row.id).order_by(AICitation.citation_order).all()
    assert [c.domain for c in cites] == ["ledgercourt.com", "rival.com"]
    assert [c.source_type for c in cites] == ["owned", "competitor"]
    assert all(c.capture_method == "prose_regex" for c in cites)
    assert sorted(row.sources_cited) == ["ledgercourt.com", "rival.com"]
    assert row.brand_mentioned is True
    assert db.query(Mention).filter_by(response_id=row.id, entity_type="property").count() == 1
    assert row.normalized_response["schema_version"] == 1
    assert row.raw_provider_payload is None  # nothing to store; not fabricated


def test_demo_provider_persists_observed_citations_queries_and_zero_cost(db):
    p = _prop(db, "Demo Court")
    row = run_query(db, p.id, "best apartments", "chatgpt", provider=DemoVisibilityProvider(), now=NOW)
    run = db.get(AIRun, row.run_id)
    assert run.provider == "demo" and run.browsed is True and run.search_operations == 1
    assert run.estimated_cost == 0.0
    cites = db.query(AICitation).filter_by(response_id=row.id).all()
    assert len(cites) == 2 and all(c.capture_method == "demo" for c in cites)
    queries = db.query(AISearchQuery).filter_by(response_id=row.id).all()
    assert len(queries) == 1 and queries[0].captured_from == "demo.search_queries"
    assert row.payload_encoding == "zlib-json" and row.raw_provider_payload


def test_failed_provider_records_failed_run_and_no_evidence(db):
    p = _prop(db, "Fail Court")
    with pytest.raises(RuntimeError):
        run_query(db, p.id, "q", "chatgpt", provider=Exploding("x"), now=NOW)
    runs = db.query(AIRun).filter_by(property_id=p.id).all()
    assert len(runs) == 1 and runs[0].status == "failed"
    assert runs[0].error_class == "provider_error" and "provider down" in runs[0].error_message
    assert runs[0].completed_at is not None
    assert db.query(AIVisibilityQuery).filter_by(property_id=p.id).count() == 0
    assert read_queries(db, p.id) == []  # legacy reader sees nothing


def test_non_browsing_run_is_discarded_but_its_spend_is_kept(db):
    p = _prop(db, "Browse Court")
    with pytest.raises(BrowsingUnavailableError):
        run_query(db, p.id, "q", "chatgpt", provider=NonBrowsing("x"), now=NOW)
    run = db.query(AIRun).filter_by(property_id=p.id).one()
    assert run.status == "discarded" and run.error_class == "browsing_unavailable"
    assert run.token_input == 77 and run.token_output == 11 and run.browsed is False
    assert db.query(AIVisibilityQuery).filter_by(property_id=p.id).count() == 0


def test_duplicate_response_in_same_repeat_group_is_flagged_not_dropped(db):
    p = _prop(db, "Dup Court")
    first = run_query(db, p.id, "q", "chatgpt", provider=FR("identical answer"), now=NOW)
    second = run_query(db, p.id, "q", "chatgpt", provider=FR("identical answer"), now=NOW)
    r1, r2 = db.get(AIRun, first.run_id), db.get(AIRun, second.run_id)
    assert r1.duplicate_of_run_id is None
    assert r2.duplicate_of_run_id == r1.id
    assert db.query(AIVisibilityQuery).filter_by(property_id=p.id).count() == 2  # both kept


def test_daily_budget_blocks_before_any_run_row(db, monkeypatch):
    monkeypatch.setattr(settings, "ai_visibility_daily_limit", 1)
    p = _prop(db, "Budget Court")
    run_query(db, p.id, "q", "chatgpt", provider=FR("one"), now=NOW)
    with pytest.raises(RateLimitExceeded):
        run_query(db, p.id, "q2", "chatgpt", provider=FR("two"), now=NOW)
    assert db.query(AIRun).filter_by(property_id=p.id).count() == 1


def test_execute_observation_requires_prompt_and_property(db):
    p = _prop(db, "Guard Court")
    with pytest.raises(ValueError):
        execute_observation(db, property_id=p.id, prompt_text="   ", platform="chatgpt", provider=FR("x"))
    with pytest.raises(ValueError):
        execute_observation(db, property_id=999999, prompt_text="q", platform="chatgpt", provider=FR("x"))


def test_query_detail_endpoint_exposes_labeled_observation(client, db):
    p = _prop(db, "Detail Court")
    row = run_query(db, p.id, "best apartments", "chatgpt", provider=DemoVisibilityProvider(), now=NOW)
    r = client.get(f"/api/ai-visibility/{p.id}/{row.id}")
    assert r.status_code == 200
    body = r.json()
    obs = body["observation"]
    assert obs["run"]["status"] == "success" and obs["run"]["provider"] == "demo"
    assert obs["citations"]["label"] == "OBSERVED" and obs["citations"]["capture"] == "provider"
    assert len(obs["citations"]["items"]) == 2
    assert obs["search_queries"]["label"] == "OBSERVED"
    assert "not consumer search volume" in obs["search_queries"]["note"]
    assert obs["run"]["cost"]["label"] == "MODELED" and obs["run"]["cost"]["estimated_usd"] == 0.0
    assert body["query"]["run_id"] == row.run_id
    assert "—" not in r.text


def test_legacy_response_detail_is_labeled_unavailable_not_observed(client, db):
    """A row stored before the run ledger has no provider evidence; the
    detail must say UNAVAILABLE rather than pretend it observed nothing."""
    p = _prop(db, "Legacy Court")
    row = AIVisibilityQuery(
        property_id=p.id, platform="chatgpt", prompt_text="q",
        raw_response_text="See https://www.hud.gov/ for details.",
        executed_at=NOW, brand_mentioned=False, sources_cited=["hud.gov"],
    )
    db.add(row)
    db.commit()
    obs = client.get(f"/api/ai-visibility/{p.id}/{row.id}").json()["observation"]
    assert obs["run"] is None
    assert obs["citations"]["label"] == "UNAVAILABLE" and obs["citations"]["capture"] == "legacy"
    assert obs["search_queries"]["label"] == "UNAVAILABLE"


def test_non_browsing_run_returns_409_not_500(client, db, monkeypatch):
    from app.services.ai_visibility import providers as providers_mod

    p = _prop(db, "Conflict Court")
    monkeypatch.setattr(providers_mod, "get_ai_visibility_provider", lambda platform=None: NonBrowsing("x"))
    r = client.post(f"/api/ai-visibility/{p.id}/query", json={"prompt": "q", "platform": "chatgpt"})
    assert r.status_code == 409
    assert r.json()["detail"] == "no browse"  # the provider's own message, verbatim
    run = db.query(AIRun).filter_by(property_id=p.id).one()
    assert run.status == "discarded" and run.token_input == 77


def test_meta_exposes_capabilities_and_labels(client):
    body = client.get("/api/ai-visibility/meta").json()
    assert "supports_citation_capture" in body["capability_keys"]
    chatgpt = next(p for p in body["platforms"] if p["key"] == "chatgpt")
    assert chatgpt["supports_search_query_capture"] is True
    copilot = next(p for p in body["platforms"] if p["key"] == "copilot")
    assert copilot["supports_citation_capture"] is False
    assert set(body["data_labels"]) == {"OBSERVED", "MEASURED", "MODELED", "UNAVAILABLE"}
