"""Chunk builder: one chunk per property x calendar month x source.

Chunk text is DETERMINISTIC and templated from real ingested rows; no model
ever writes chunk content. Each chunk carries enough identifying context
(property, source, period) to be retrieved and cited on its own, and AI
traffic chunks embed the undercount disclosure so retrieval-grounded answers
inherit it naturally.
"""

import hashlib
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.connectors.base import ContentProvider
from app.constants import AI_TRAFFIC_DISCLOSURE
from app.models import (
    CRMLead,
    GA4SessionsDaily,
    GBPMetricsDaily,
    GSCPerformanceDaily,
    PaidMediaDaily,
    Property,
)
from app.services.classifier import get_classifier

# Logical source key per builder (distinct from the DB source_table). These
# match the upload SourceType values so a scoped sync job can filter by source.
SOURCE_GA4 = "ga4"
SOURCE_GSC = "gsc"
SOURCE_GBP = "gbp"
SOURCE_PAID = "paid_media"
SOURCE_CRM = "crm"
SOURCE_CONTENT = "content"
SOURCE_CONTENT_INTELLIGENCE = "content_intelligence"
SOURCE_PROPERTY_CONTEXT = "property_context"
SOURCE_REVIEWS = "reviews"
SOURCE_REVIEW_INTELLIGENCE = "review_intelligence"
SOURCE_AI_QUERY_SIGNALS = "ai_query_signals"
SOURCE_AI_VISIBILITY = "ai_visibility"
SOURCE_COMPETITOR_INTELLIGENCE = "competitor_intelligence"
SOURCE_OPPORTUNITY_ENGINE = "opportunity_engine"
SOURCE_SEO_PERFORMANCE = "seo_performance"


@dataclass(frozen=True)
class Chunk:
    chroma_id: str
    property_id: int
    source: str
    source_table: str
    source_ref: str
    period_start: date | None
    period_end: date | None
    text: str
    page: str | None = None

    @property
    def text_hash(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _period_bounds(dates: list[date]) -> tuple[date, date]:
    return min(dates), max(dates)


def _prop_header(prop: Property) -> str:
    location = ", ".join(x for x in (prop.city, prop.state) if x)
    return f"Property: {prop.name}" + (f" ({location})." if location else ".")


def _group_by_month(rows, date_attr: str) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(_month_key(getattr(row, date_attr)), []).append(row)
    return grouped


def _make_chunk(prop, table: str, source: str, month: str, dates, body: str) -> Chunk:
    start, end = _period_bounds(dates)
    return Chunk(
        chroma_id=f"{table}-p{prop.id}-{month}",
        property_id=prop.id,
        source=source,
        source_table=table,
        source_ref=f"{table}: property={prop.id}, month={month}",
        period_start=start,
        period_end=end,
        text=body,
    )


def _ga4_chunks(db: Session, prop: Property) -> list[Chunk]:
    rows = db.query(GA4SessionsDaily).filter_by(property_id=prop.id).all()
    labels = {p.key: p.label for p in get_classifier().platforms}
    chunks = []
    for month, month_rows in sorted(_group_by_month(rows, "date").items()):
        sessions = sum(r.sessions for r in month_rows)
        ai_rows = [r for r in month_rows if r.is_ai_referral]
        ai_sessions = sum(r.sessions for r in ai_rows)
        key_events = sum(r.key_events for r in month_rows)
        ai_key_events = sum(r.key_events for r in ai_rows)
        share = f"{(ai_sessions / sessions * 100):.1f}%" if sessions else "0%"

        mix: dict[str, int] = {}
        for r in ai_rows:
            mix[r.ai_platform] = mix.get(r.ai_platform, 0) + r.sessions
        mix_text = (
            "; ".join(
                f"{labels.get(k, k)} {v} sessions"
                for k, v in sorted(mix.items(), key=lambda kv: -kv[1])
            )
            or "none detected"
        )

        top_sources: dict[str, int] = {}
        for r in month_rows:
            key = f"{r.session_source}/{r.session_medium}"
            top_sources[key] = top_sources.get(key, 0) + r.sessions
        top_text = "; ".join(
            f"{k} {v} sessions"
            for k, v in sorted(top_sources.items(), key=lambda kv: -kv[1])[:8]
        )

        dates = [r.date for r in month_rows]
        start, end = _period_bounds(dates)
        body = (
            f"{_prop_header(prop)} Source: GA4 website traffic (manual upload). "
            f"Period: {start.isoformat()} to {end.isoformat()}.\n"
            f"Total sessions: {sessions}. Key events (conversions): {key_events}.\n"
            f"AI referral sessions: {ai_sessions} ({share} of sessions). "
            f"Key events from AI traffic: {ai_key_events}.\n"
            f"AI platform breakdown: {mix_text}.\n"
            f"Top traffic sources: {top_text}.\n"
            f"Note: {AI_TRAFFIC_DISCLOSURE}"
        )
        chunks.append(
            _make_chunk(prop, "ga4_sessions_daily", SOURCE_GA4, month, dates, body)
        )
    return chunks


def _gsc_chunks(db: Session, prop: Property) -> list[Chunk]:
    rows = db.query(GSCPerformanceDaily).filter_by(property_id=prop.id).all()
    chunks = []
    for month, month_rows in sorted(_group_by_month(rows, "date").items()):
        clicks = sum(r.clicks for r in month_rows)
        impressions = sum(r.impressions for r in month_rows)
        ctr = f"{(clicks / impressions * 100):.2f}%" if impressions else "0%"
        position = (
            sum(r.position * r.impressions for r in month_rows) / impressions
            if impressions
            else 0
        )
        queries = sorted(
            (
                (r.query, r.clicks)
                for r in month_rows
                if r.query
            ),
            key=lambda kv: -kv[1],
        )[:8]
        query_text = (
            " Top queries: " + "; ".join(f"'{q}' {c} clicks" for q, c in queries) + "."
            if queries
            else ""
        )
        dates = [r.date for r in month_rows]
        start, end = _period_bounds(dates)
        body = (
            f"{_prop_header(prop)} Source: Google Search Console organic search "
            f"performance (manual upload). Period: {start.isoformat()} to {end.isoformat()}.\n"
            f"Organic clicks: {clicks}. Impressions: {impressions}. CTR: {ctr}. "
            f"Average position: {position:.1f}.{query_text}"
        )
        chunks.append(
            _make_chunk(prop, "gsc_performance_daily", SOURCE_GSC, month, dates, body)
        )
    return chunks


def _gbp_chunks(db: Session, prop: Property) -> list[Chunk]:
    rows = db.query(GBPMetricsDaily).filter_by(property_id=prop.id).all()
    chunks = []
    for month, month_rows in sorted(_group_by_month(rows, "date").items()):
        dates = [r.date for r in month_rows]
        start, end = _period_bounds(dates)
        body = (
            f"{_prop_header(prop)} Source: Google Business Profile performance "
            f"(manual upload). Period: {start.isoformat()} to {end.isoformat()}.\n"
            f"Search impressions: {sum(r.search_impressions for r in month_rows)}. "
            f"Maps impressions: {sum(r.maps_impressions for r in month_rows)}. "
            f"Website clicks: {sum(r.website_clicks for r in month_rows)}. "
            f"Calls: {sum(r.calls for r in month_rows)}. "
            f"Direction requests: {sum(r.direction_requests for r in month_rows)}."
        )
        chunks.append(
            _make_chunk(prop, "gbp_metrics_daily", SOURCE_GBP, month, dates, body)
        )
    return chunks


def _paid_chunks(db: Session, prop: Property) -> list[Chunk]:
    rows = db.query(PaidMediaDaily).filter_by(property_id=prop.id).all()
    chunks = []
    for month, month_rows in sorted(_group_by_month(rows, "date").items()):
        by_platform: dict[str, dict] = {}
        for r in month_rows:
            agg = by_platform.setdefault(
                r.platform, {"spend": 0.0, "clicks": 0, "conversions": 0.0}
            )
            agg["spend"] += float(r.spend)
            agg["clicks"] += r.clicks
            agg["conversions"] += r.conversions
        platform_text = "; ".join(
            f"{k}: ${v['spend']:.2f} spend, {v['clicks']} clicks, "
            f"{v['conversions']:.1f} conversions"
            for k, v in sorted(by_platform.items())
        )
        dates = [r.date for r in month_rows]
        start, end = _period_bounds(dates)
        body = (
            f"{_prop_header(prop)} Source: paid media campaign reports "
            f"(manual upload). Period: {start.isoformat()} to {end.isoformat()}.\n"
            f"Paid media by platform: {platform_text}."
        )
        chunks.append(
            _make_chunk(prop, "paid_media_daily", SOURCE_PAID, month, dates, body)
        )
    return chunks


def _crm_chunks(db: Session, prop: Property) -> list[Chunk]:
    rows = db.query(CRMLead).filter_by(property_id=prop.id).all()
    chunks = []
    for month, month_rows in sorted(
        _group_by_month(rows, "first_contact_date").items()
    ):
        funnel = {"lead": 0, "tour": 0, "application": 0, "lease": 0, "lost": 0}
        sources: dict[str, int] = {}
        for r in month_rows:
            funnel[r.status.value] += 1
            sources[r.lead_source_raw] = sources.get(r.lead_source_raw, 0) + 1
        source_text = "; ".join(
            f"{k}: {v}" for k, v in sorted(sources.items(), key=lambda kv: -kv[1])
        )
        dates = [r.first_contact_date for r in month_rows]
        start, end = _period_bounds(dates)
        body = (
            f"{_prop_header(prop)} Source: CRM lead export (manual upload). "
            f"Period of first contact: {start.isoformat()} to {end.isoformat()}.\n"
            f"Leads: {len(month_rows)}. Funnel by furthest stage reached: "
            f"{funnel['lead']} lead, {funnel['tour']} tour, "
            f"{funnel['application']} application, {funnel['lease']} lease, "
            f"{funnel['lost']} lost.\n"
            f"Lead sources as recorded in the CRM: {source_text}."
        )
        chunks.append(_make_chunk(prop, "crm_leads", SOURCE_CRM, month, dates, body))
    return chunks


def _content_chunks(
    db: Session, prop: Property, content_provider: ContentProvider
) -> list[Chunk]:
    """Content pages (homepage, FAQ, amenities, neighborhood) sourced through a
    ContentProvider. The current DevelopmentDataProvider returns nothing, so
    this yields no chunks today; a future content connector lights it up with
    no change here."""
    chunks = []
    for rec in content_provider.get_content(db, prop.id):
        updated = rec.updated_at.date() if rec.updated_at else None
        body = (
            f"{_prop_header(prop)} Source: website content, page: {rec.page}.\n"
            f"{rec.title}\n{rec.body}"
        )
        chunks.append(
            Chunk(
                chroma_id=f"content-p{prop.id}-{rec.page}",
                property_id=prop.id,
                source=SOURCE_CONTENT,
                source_table="property_content",
                source_ref=f"content: property={prop.id}, page={rec.page}",
                period_start=updated,
                period_end=updated,
                text=body,
                page=rec.page,
            )
        )
    return chunks


def _ci_chunks(
    db: Session, prop: Property, content_provider: ContentProvider
) -> list[Chunk]:
    """One deterministic Content Intelligence summary chunk per property, so
    Nora can answer content questions with citations. Empty when the property
    has no ingested content."""
    from app.services.content_intelligence import (
        analyze_property,
        content_intelligence_summary_text,
    )

    analysis = analyze_property(db, prop.id, content_provider=content_provider)
    text = content_intelligence_summary_text(analysis)
    if not text:
        return []
    return [
        Chunk(
            chroma_id=f"content_intelligence-p{prop.id}",
            property_id=prop.id,
            source=SOURCE_CONTENT_INTELLIGENCE,
            source_table="content_intelligence",
            source_ref=f"content_intelligence: property={prop.id}",
            period_start=None,
            period_end=None,
            text=text,
            page=None,
        )
    ]


def _ai_visibility_chunks(db: Session, prop: Property) -> list[Chunk]:
    """One deterministic AI Visibility summary chunk per property, so Nora
    answers 'how do we show up in ChatGPT' with directional, sample-size-aware
    language. Empty when no queries have been run for the property."""
    from app.services.ai_visibility import ai_visibility_summary_text

    text = ai_visibility_summary_text(db, prop.id)
    if not text:
        return []
    return [
        Chunk(
            chroma_id=f"ai_visibility-p{prop.id}",
            property_id=prop.id,
            source=SOURCE_AI_VISIBILITY,
            source_table="ai_visibility",
            source_ref=f"ai_visibility: property={prop.id}",
            period_start=None,
            period_end=None,
            text=text,
            page=None,
        )
    ]


def _competitor_intelligence_chunks(db: Session, prop: Property) -> list[Chunk]:
    """One deterministic Competitor Intelligence (share-of-voice) chunk per
    property, so Nora answers competitive-visibility questions with directional
    language. Empty unless competitors are tracked AND AI Visibility data
    exists."""
    from app.services.competitor_intelligence import (
        competitor_intelligence_summary_text,
    )

    text = competitor_intelligence_summary_text(db, prop.id)
    if not text:
        return []
    return [
        Chunk(
            chroma_id=f"competitor_intelligence-p{prop.id}",
            property_id=prop.id,
            source=SOURCE_COMPETITOR_INTELLIGENCE,
            source_table="competitor_intelligence",
            source_ref=f"competitor_intelligence: property={prop.id}",
            period_start=None,
            period_end=None,
            text=text,
            page=None,
        )
    ]


def _opportunity_engine_chunks(
    db: Session, prop: Property, content_provider: ContentProvider
) -> list[Chunk]:
    """One deterministic unified-opportunities chunk per property, so Nora
    answers 'what should we do first' from the ranked cross-module list. Empty
    when no module has produced a recommendation."""
    from app.services.opportunity_engine import opportunity_engine_summary_text

    text = opportunity_engine_summary_text(db, prop.id, content_provider=content_provider)
    if not text:
        return []
    return [
        Chunk(
            chroma_id=f"opportunity_engine-p{prop.id}",
            property_id=prop.id,
            source=SOURCE_OPPORTUNITY_ENGINE,
            source_table="opportunity_engine",
            source_ref=f"opportunity_engine: property={prop.id}",
            period_start=None,
            period_end=None,
            text=text,
            page=None,
        )
    ]


def _seo_performance_chunks(db: Session, prop: Property) -> list[Chunk]:
    """One deterministic SEO-performance chunk per property (striking-distance
    queries by name with position/impressions/clicks, low-CTR queries, and
    movers), so Nora can answer the briefing's own strategic questions instead
    of only knowing that such queries exist. Empty without query data."""
    from app.services.reporting_seo import seo_performance_summary_text

    text = seo_performance_summary_text(db, prop.id)
    if not text:
        return []
    return [
        Chunk(
            chroma_id=f"seo_performance-p{prop.id}",
            property_id=prop.id,
            source=SOURCE_SEO_PERFORMANCE,
            source_table="seo_performance",
            source_ref=f"seo_performance: property={prop.id}",
            period_start=None,
            period_end=None,
            text=text,
            page=None,
        )
    ]


def _property_context_chunks(db: Session, prop: Property) -> list[Chunk]:
    """One verbatim property-context chunk per configured property, so Nora
    grounds context answers in retrieved text rather than inference. Empty when
    the operator has not authored context (no profile row)."""
    from app.services.property_context import (
        get_property_context,
        property_context_chunk_text,
    )

    context = get_property_context(db, prop.id)
    if not context["configured"]:
        return []
    return [
        Chunk(
            chroma_id=f"property_context-p{prop.id}",
            property_id=prop.id,
            source=SOURCE_PROPERTY_CONTEXT,
            source_table="property_context",
            source_ref=f"property_context: property={prop.id}",
            period_start=None,
            period_end=None,
            text=property_context_chunk_text(context),
            page=None,
        )
    ]


def _review_chunks(db: Session, prop: Property, review_provider) -> list[Chunk]:
    """One chunk per review, for citation fidelity (Nora can cite an individual
    review). Empty when the property has no reviews."""
    chunks = []
    for rec in review_provider.get_reviews(db, prop.id):
        rating = f"{rec.rating} stars" if rec.rating is not None else "no rating"
        rdate = rec.published_at.date().isoformat() if rec.published_at else "unknown date"
        body = (
            f"Resident review of {prop.name} ({rec.provider}, {rdate}, {rating}).\n"
            f"{(rec.title + '. ') if rec.title else ''}{rec.text}"
            + (f"\nOwner response: {rec.response_text}" if rec.response_text else "")
        )
        chunks.append(
            Chunk(
                chroma_id=f"review-p{prop.id}-{rec.review_id}",
                property_id=prop.id,
                source=SOURCE_REVIEWS,
                source_table="property_reviews",
                source_ref=f"review: property={prop.id}, review_id={rec.review_id}, provider={rec.provider}",
                period_start=rec.published_at.date() if rec.published_at else None,
                period_end=rec.published_at.date() if rec.published_at else None,
                text=body,
                page=None,
            )
        )
    return chunks


def _review_intelligence_chunks(db: Session, prop: Property, review_provider) -> list[Chunk]:
    """One deterministic Review Intelligence summary chunk per property, so Nora
    answers review questions with citations and grounds disclaimers in the
    verbatim insufficient-data text. Empty when the property has no reviews."""
    from app.services.review_intelligence import (
        analyze_property_reviews,
        review_intelligence_summary_text,
    )

    analysis = analyze_property_reviews(db, prop.id, review_provider=review_provider)
    text = review_intelligence_summary_text(analysis)
    if not text:
        return []
    return [
        Chunk(
            chroma_id=f"review_intelligence-p{prop.id}",
            property_id=prop.id,
            source=SOURCE_REVIEW_INTELLIGENCE,
            source_table="review_intelligence",
            source_ref=f"review_intelligence: property={prop.id}",
            period_start=None,
            period_end=None,
            text=text,
            page=None,
        )
    ]


def _ai_query_signals_chunks(
    db: Session, prop: Property, content_provider: ContentProvider
) -> list[Chunk]:
    """One deterministic AI Query Signals summary chunk per property, so Nora
    answers AI-traffic questions with citations and inherits the exact-prompt
    limitation verbatim. Empty when the property has no AI-referred traffic."""
    from app.services.ai_query_signals import (
        ai_query_signals_summary_text,
        analyze_ai_query_signals,
    )

    analysis = analyze_ai_query_signals(
        db, prop.id, content_provider=content_provider
    )
    text = ai_query_signals_summary_text(analysis)
    if not text:
        return []
    dr = analysis["overview"]["date_range"]
    return [
        Chunk(
            chroma_id=f"ai_query_signals-p{prop.id}",
            property_id=prop.id,
            source=SOURCE_AI_QUERY_SIGNALS,
            source_table="ai_query_signals",
            source_ref=f"ai_query_signals: property={prop.id}",
            period_start=date.fromisoformat(dr["start"]),
            period_end=date.fromisoformat(dr["end"]),
            text=text,
            page=None,
        )
    ]


_BUILDERS = {
    SOURCE_GA4: _ga4_chunks,
    SOURCE_GSC: _gsc_chunks,
    SOURCE_GBP: _gbp_chunks,
    SOURCE_PAID: _paid_chunks,
    SOURCE_CRM: _crm_chunks,
}


def build_chunks(
    db: Session,
    property_id: int | None = None,
    sources: list[str] | None = None,
    content_provider: ContentProvider | None = None,
    review_provider=None,
) -> list[Chunk]:
    """Deterministic chunks. With no filters, every chunk for every property
    (back-compatible). `property_id` and `sources` scope the build so the sync
    service can rebuild only what a given change affected. `content_provider`
    adds content-page + Content Intelligence chunks; `review_provider` adds
    per-review + Review Intelligence chunks, when in scope."""
    props = db.query(Property).order_by(Property.id)
    if property_id is not None:
        props = props.filter(Property.id == property_id)

    def want(src: str) -> bool:
        return sources is None or src in sources

    chunks: list[Chunk] = []
    for prop in props.all():
        for src, builder in _BUILDERS.items():
            if want(src):
                chunks.extend(builder(db, prop))
        if want(SOURCE_PROPERTY_CONTEXT):
            chunks.extend(_property_context_chunks(db, prop))
        if want(SOURCE_AI_VISIBILITY):
            chunks.extend(_ai_visibility_chunks(db, prop))
        if want(SOURCE_COMPETITOR_INTELLIGENCE):
            chunks.extend(_competitor_intelligence_chunks(db, prop))
        if want(SOURCE_SEO_PERFORMANCE):
            chunks.extend(_seo_performance_chunks(db, prop))
        if content_provider is not None:
            if want(SOURCE_CONTENT):
                chunks.extend(_content_chunks(db, prop, content_provider))
            if want(SOURCE_CONTENT_INTELLIGENCE):
                chunks.extend(_ci_chunks(db, prop, content_provider))
            if want(SOURCE_AI_QUERY_SIGNALS):
                chunks.extend(_ai_query_signals_chunks(db, prop, content_provider))
            if want(SOURCE_OPPORTUNITY_ENGINE):
                chunks.extend(_opportunity_engine_chunks(db, prop, content_provider))
        if review_provider is not None:
            if want(SOURCE_REVIEWS):
                chunks.extend(_review_chunks(db, prop, review_provider))
            if want(SOURCE_REVIEW_INTELLIGENCE):
                chunks.extend(_review_intelligence_chunks(db, prop, review_provider))
    return chunks
