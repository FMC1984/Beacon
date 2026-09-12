"""Execute one AI observation end to end (Phase 19).

    prompt -> provider -> ProviderResult -> AIRun (ledger, always written)
           -> AIVisibilityQuery (evidence, success only)
           -> citations + retrieval queries (OBSERVED)
           -> mentions (deterministic)
           -> cost (MODELED or UNAVAILABLE)

The run row is written BEFORE the provider is called, so a crash or a
provider error still leaves an auditable attempt with whatever tokens it
burned. Failed and discarded runs are kept and count as spend; only
successful responses become evidence rows, which is what keeps every legacy
reader of ai_visibility_queries correct without a status filter.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.connectors.base import AIVisibilityQueryProvider, ProviderResult, ProviderUsage
from app.extensions.hooks import trigger_rag_sync
from app.models import (
    AICitation,
    AIRun,
    AISearchQuery,
    AIVisibilityPrompt,
    AIVisibilityQuery,
    Competitor,
    Property,
)
from app.models.ai_runs import (
    RUN_DISCARDED,
    RUN_FAILED,
    RUN_RUNNING,
    RUN_SUCCESS,
    SCOPE_PROPERTY,
)
from app.services.ai_visibility.mentions import persist_mentions_for_query, resolve_property_terms
from app.services.ai_visibility.parsing import detect_mention, extract_sources
from app.services.ai_visibility.reference import validate_platform
from app.services.observatory import LABEL_OBSERVED, LABEL_UNAVAILABLE
from app.services.observatory.budgets import record_spend
from app.services.observatory.tenancy import property_org_id
from app.services.observatory.citations import (
    citation_domains,
    competitor_domains_for,
    extract_citations,
    owned_domains_for,
    persist_citations,
)
from app.services.observatory.observability import log_event
from app.services.observatory.pricing import cost_label, estimate_cost
from app.services.observatory.provider_result import (
    PAYLOAD_ENCODING,
    compress_payload,
    normalize_result,
    response_hash,
)
from app.services.observatory.search_queries import persist_search_queries

_RATE_LIMIT_CLASSES = {"RateLimitError"}
_RETRYABLE_CLASSES = {"APIConnectionError", "APITimeoutError", "InternalServerError"}


@dataclass
class Observation:
    run: AIRun
    response: AIVisibilityQuery | None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def classify_error(exc: BaseException) -> str:
    """Map a provider exception onto a stable error_class without importing
    optional SDKs at module import time."""
    name = type(exc).__name__
    if name in _RATE_LIMIT_CLASSES:
        return "rate_limit"
    if name == "BrowsingUnavailableError":
        return "browsing_unavailable"
    if name == "PlatformNotConnectedError":
        return "platform_not_connected"
    if name in _RETRYABLE_CLASSES:
        return "provider_unavailable"
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return "provider_error_5xx" if status >= 500 else "provider_error_4xx"
    return "provider_error"


def _apply_usage(run: AIRun, result: ProviderResult | None) -> None:
    if result is None:
        return
    u: ProviderUsage = result.usage
    run.model = result.model or run.model
    run.token_input = u.input_tokens
    run.token_output = u.output_tokens
    run.token_reasoning = u.reasoning_tokens
    run.token_cached = u.cached_tokens
    run.search_operations = result.search_operations or 0
    run.browsed = result.browsed
    run.latency_ms = result.latency_ms
    run.provider_response_id = result.provider_response_id
    run.estimated_cost, run.pricing_version = estimate_cost(
        run.provider, run.model, u, run.search_operations
    )


INLINE_ROLLUP_MAX_PROPERTIES = 50


def _refresh_rollups(db: Session, response: AIVisibilityQuery, property_ids: list[int]) -> None:
    """Keep dashboards current: small fan-outs roll up inline (a few SQL
    statements), large ones are handed to the jobs runner."""
    if not property_ids:
        return
    from app.services.observatory.rollups import update_property_rollups

    if len(property_ids) <= INLINE_ROLLUP_MAX_PROPERTIES:
        update_property_rollups(db, property_ids=property_ids)
        return
    from app.services.jobs.queue import enqueue

    enqueue(
        db, "update_property_rollups", {"property_ids": property_ids},
        idempotency_key=f"rollup:response:{response.id}", market_id=response.market_id,
        organization_id=response.organization_id,
    )


def _extract_intelligence(db: Session, response: AIVisibilityQuery, run: AIRun, observations, prop) -> None:
    """Claims about mentioned properties and competitor candidates in the
    market: deterministic text rules over the stored answer. A failure here
    is logged and never loses the stored observation."""
    from app.services.observatory.claims import persist_claims_for_response
    from app.services.observatory.discovery import discover_from_response

    try:
        mentioned = [o.property_id for o in observations if o.mentioned]
        if mentioned:
            persist_claims_for_response(db, response, mentioned)
        market_id = run.market_id or (prop.market_id if prop is not None else None)
        discover_from_response(db, response, market_id)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log_event("intelligence.failed", response_id=response.id, error=str(exc)[:300])


def execute_observation(
    db: Session,
    *,
    property_id: int | None,
    prompt_text: str,
    platform: str,
    run_scope: str = SCOPE_PROPERTY,
    prompt_id: int | None = None,
    organization_id: int | None = None,
    market_id: int | None = None,
    repeat_index: int = 0,
    provider: AIVisibilityQueryProvider | None = None,
    job_id: int | None = None,
    now: datetime | None = None,
) -> Observation:
    """Run one prompt against one platform and persist everything. Raises the
    provider error after recording the failed run, so callers keep today's
    exception semantics (schedule.py catches per prompt; the router maps to
    HTTP codes)."""
    from app.services.ai_visibility.execution import RateLimitExceeded, queries_used_today
    from app.services.ai_visibility.providers import get_ai_visibility_provider
    from app.config import settings

    from app.services.observatory.budgets import budget_summary
    from app.services.observatory.tenancy import default_organization_id

    prompt_text = (prompt_text or "").strip()
    if not prompt_text:
        raise ValueError("Prompt is empty.")
    platform = validate_platform(platform)
    now = now or _utcnow()

    prop: Property | None = None
    if run_scope == SCOPE_PROPERTY or property_id is not None:
        prop = db.get(Property, property_id) if property_id is not None else None
        if prop is None:
            raise ValueError("Property not found.")
        used = queries_used_today(db, property_id, now)
        limit = settings.ai_visibility_daily_limit
        if used >= limit:
            log_event(
                "run.budget_exhausted", property_id=property_id, used=used, limit=limit
            )
            raise RateLimitExceeded(
                f"Daily AI Visibility query budget reached for this property "
                f"({used}/{limit}). Queries are paused until tomorrow (UTC) so "
                "external-API cost stays bounded."
            )
    elif market_id is None:
        raise ValueError("A market run needs a market_id.")

    if organization_id is None:
        organization_id = property_org_id(db, property_id) if property_id is not None else default_organization_id(db)
    if property_id is None:
        # Market runs have no per-property daily cap; the organization's
        # monthly observation budget is the stop.
        summary = budget_summary(db, "org", organization_id)
        if summary["exhausted"]:
            log_event("run.org_budget_exhausted", organization_id=organization_id, **{
                k: summary[k] for k in ("period", "allowance_runs", "spent_runs")})
            raise RateLimitExceeded(
                f"Monthly observation budget reached for this organization "
                f"({summary['spent_runs']}/{summary['allowance_runs']} runs in {summary['period']})."
            )

    provider = provider or get_ai_visibility_provider(platform)
    provider_key = getattr(provider, "name", "unknown")
    requested_model = getattr(provider, "model", None)

    run = AIRun(
        organization_id=organization_id,
        prompt_id=prompt_id,
        market_id=market_id,
        property_id=property_id,
        run_scope=run_scope,
        platform=platform,
        provider=provider_key,
        model_requested=requested_model,
        model=requested_model,
        repeat_index=repeat_index,
        repeat_group_key=f"{prompt_id or response_hash(prompt_text)[:16]}:{platform}:{now.date().isoformat()}",
        job_id=job_id,
        status=RUN_RUNNING,
        started_at=now,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    started = time.perf_counter()
    try:
        # The ONLY non-deterministic step in Beacon.
        result = provider.execute(prompt_text, platform)
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        error_class = classify_error(exc)
        run.status = RUN_DISCARDED if error_class == "browsing_unavailable" else RUN_FAILED
        run.error_class = error_class
        run.error_message = str(exc)[:2000]
        run.completed_at = _utcnow()
        partial = getattr(exc, "result", None)
        if isinstance(partial, ProviderResult):
            _apply_usage(run, partial)
        if run.latency_ms is None:
            run.latency_ms = elapsed_ms
        record_spend(db, run, run.organization_id)
        db.commit()
        log_event(
            "run.failed", run_id=run.id, provider=provider_key, platform=platform,
            property_id=property_id, prompt_id=prompt_id, status=run.status,
            error_class=error_class, latency_ms=run.latency_ms,
            tokens_in=run.token_input, tokens_out=run.token_output,
            search_operations=run.search_operations, estimated_cost=run.estimated_cost,
        )
        raise

    if result.latency_ms is None:
        result = ProviderResult(
            **{**result.__dict__, "latency_ms": int((time.perf_counter() - started) * 1000)}
        )

    raw = result.text or ""
    from app.services.observatory.derivation import derive_observations, eligible_properties
    from app.services.observatory.entities import (
        detect_entity_mentions,
        entities_for_properties,
        persist_entity_mentions,
    )

    prompt_row = db.get(AIVisibilityPrompt, prompt_id) if prompt_id else None
    scored = eligible_properties(db, run, prompt_row)
    scored_props = [p for p, _ in scored]
    competitors = (
        db.query(Competitor).filter_by(property_id=property_id).all()
        if property_id is not None
        else db.query(Competitor).filter(Competitor.property_id.in_([p.id for p in scored_props])).all()
        if scored_props else []
    )
    drafts = extract_citations(result, raw)
    # Legacy domain list: union of provider-reported citation domains and the
    # prose extraction, so older readers see at least what they saw before.
    sources = sorted(set(extract_sources(raw)) | set(citation_domains(drafts)))
    brand_mentioned = bool(prop) and detect_mention(raw, resolve_property_terms(prop))

    row = AIVisibilityQuery(
        property_id=property_id,
        platform=platform,
        prompt_text=prompt_text,
        raw_response_text=raw,
        executed_at=now,
        brand_mentioned=brand_mentioned,
        sources_cited=sources,
        execution_status="success",
        model_metadata={"connector": provider_key, "model": result.model},
        run_id=run.id,
        prompt_id=prompt_id,
        market_id=market_id,
        organization_id=organization_id,
        run_scope=run_scope,
        provider=provider_key,
        model=result.model,
        response_hash=response_hash(raw),
        normalized_response=normalize_result(result),
        raw_provider_payload=compress_payload(result.raw_payload),
        payload_encoding=PAYLOAD_ENCODING if result.raw_payload is not None else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    owned = owned_domains_for(prop) if prop else {d for p in scored_props for d in owned_domains_for(p)}
    persist_citations(db, row, run, drafts, owned, competitor_domains_for(competitors))
    persist_search_queries(
        db, row, run, result.search_queries,
        captured_from=f"{provider_key}.search_queries",
    )
    db.commit()
    if property_id is not None:
        persist_mentions_for_query(db, row)  # legacy per-property semantics, unchanged
    else:
        entities = entities_for_properties(db, scored_props)
        persist_entity_mentions(db, row, run, detect_entity_mentions(raw, entities))
        db.commit()
    observations = derive_observations(db, row, run, scored)
    db.commit()
    _refresh_rollups(db, row, [o.property_id for o in observations])
    _extract_intelligence(db, row, run, observations, prop)

    _apply_usage(run, result)
    run.status = RUN_SUCCESS
    run.response_hash = row.response_hash
    run.completed_at = _utcnow()
    duplicate = (
        db.query(AIRun)
        .filter(
            AIRun.repeat_group_key == run.repeat_group_key,
            AIRun.response_hash == run.response_hash,
            AIRun.id != run.id,
            AIRun.status == RUN_SUCCESS,
        )
        .order_by(AIRun.id)
        .first()
    )
    if duplicate is not None:
        run.duplicate_of_run_id = duplicate.id
    record_spend(db, run, run.organization_id)
    db.commit()

    log_event(
        "run.success", run_id=run.id, response_id=row.id, provider=provider_key,
        platform=platform, property_id=property_id, prompt_id=prompt_id,
        latency_ms=run.latency_ms, tokens_in=run.token_input,
        tokens_out=run.token_output, search_operations=run.search_operations,
        estimated_cost=run.estimated_cost, citations=len(drafts),
        search_queries=len(result.search_queries), browsed=run.browsed,
        market_id=market_id, properties_scored=len(observations),
    )
    if property_id is not None:
        trigger_rag_sync(
            db, property_id=property_id, source="ai_visibility", reason="ai_visibility_query"
        )
    return Observation(run=run, response=row)


def execute_market_prompt(
    db: Session, prompt_id: int, *, platform: str | None = None,
    provider: AIVisibilityQueryProvider | None = None, now: datetime | None = None,
    repeat_index: int = 0, job_id: int | None = None,
) -> Observation:
    """Run one shared market/feature prompt once; every property subscribed
    to its cluster is scored from the single answer."""
    prompt = db.get(AIVisibilityPrompt, prompt_id)
    if prompt is None:
        raise ValueError("Prompt not found.")
    if prompt.property_id is not None or prompt.market_id is None:
        raise ValueError("Not a market-scope prompt.")
    if not prompt.active or not prompt.approved:
        raise ValueError("Prompt is inactive or not approved.")
    return execute_observation(
        db, property_id=None, prompt_text=prompt.prompt_text, platform=platform or prompt.platform,
        run_scope=prompt.scope, prompt_id=prompt.id, organization_id=prompt.organization_id,
        market_id=prompt.market_id, repeat_index=repeat_index, provider=provider, job_id=job_id, now=now,
    )


def run_detail(run: AIRun | None) -> dict | None:
    if run is None:
        return None
    return {
        "id": run.id,
        "status": run.status,
        "provider": run.provider,
        "platform": run.platform,
        "model": run.model,
        "model_requested": run.model_requested,
        "run_scope": run.run_scope,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "latency_ms": run.latency_ms,
        "browsed": run.browsed,
        "error_class": run.error_class,
        "error_message": run.error_message,
        "duplicate_of_run_id": run.duplicate_of_run_id,
        "tokens": {
            "label": LABEL_OBSERVED if run.token_input is not None else LABEL_UNAVAILABLE,
            "input": run.token_input,
            "output": run.token_output,
            "reasoning": run.token_reasoning,
            "cached": run.token_cached,
            "search_operations": run.search_operations,
        },
        "cost": {
            "label": cost_label(run.estimated_cost),
            "estimated_usd": run.estimated_cost,
            "pricing_version": run.pricing_version,
            "note": (
                "Estimated from provider-reported usage and the configured rate table."
                if run.estimated_cost is not None
                else "No rate is configured for this model, so no dollar figure is shown."
            ),
        },
    }


def observation_detail(db: Session, response: AIVisibilityQuery) -> dict:
    """Evidence block for one stored response: the run ledger row, the
    provider-reported citations and retrieval queries, each labeled."""
    run = db.get(AIRun, response.run_id) if response.run_id else None
    citations = (
        db.query(AICitation)
        .filter_by(response_id=response.id)
        .order_by(AICitation.citation_order)
        .all()
    )
    queries = (
        db.query(AISearchQuery)
        .filter_by(response_id=response.id)
        .order_by(AISearchQuery.query_order)
        .all()
    )
    provider_reported = any(c.capture_method != "prose_regex" for c in citations)
    legacy = run is None and not citations and not queries
    if legacy:
        capture, citation_label, citation_note = (
            "legacy",
            LABEL_UNAVAILABLE,
            "Stored before provider evidence capture; the sources listed above "
            "were found in the response text, and no provider-reported "
            "citations exist for it.",
        )
    elif provider_reported:
        capture, citation_label, citation_note = (
            "provider", LABEL_OBSERVED,
            "Sources the provider itself reported for this API response.",
        )
    elif citations:
        capture, citation_label, citation_note = (
            "prose_regex", LABEL_OBSERVED,
            "This provider reported no citations; these URLs were found in the response text.",
        )
    else:
        capture, citation_label, citation_note = (
            "none", LABEL_OBSERVED,
            "No citations were reported or found for this response.",
        )
    return {
        "run": run_detail(run),
        "citations": {
            "label": citation_label,
            "capture": capture,
            "note": citation_note,
            "items": [
                {
                    "url": c.url,
                    "domain": c.domain,
                    "root_domain": c.root_domain,
                    "title": c.title,
                    "order": c.citation_order,
                    "position": c.citation_position,
                    "source_type": c.source_type,
                    "capture_method": c.capture_method,
                }
                for c in citations
            ],
        },
        "search_queries": {
            "label": LABEL_UNAVAILABLE if legacy else LABEL_OBSERVED,
            "note": (
                "Stored before provider evidence capture; no retrieval queries were recorded."
                if legacy
                else "Retrieval queries the provider reported issuing for this API call. "
                "Observed provider behavior, not consumer search volume."
            ),
            "items": [
                {"query": q.query_text, "order": q.query_order, "captured_from": q.captured_from}
                for q in queries
            ],
        },
    }
