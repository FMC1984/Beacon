"""AI Share of Voice report (Phase 18).

AI Share of Voice = Property Mentions / (Property + Competitor Mentions).
Deliberately distinct from AI Visibility (analyze_ai_visibility - how often
the property appears in eligible tested responses, no competitor standing
involved) and Citation Share (not yet built - share of the citation/source
ecosystem). These three metrics are never fused.

Reads from persisted Mention rows (ai_visibility/mentions.py), not a live
regex re-scan, so every number here is an indexed aggregate over evidence
that can be walked back down to the individual response and mention record
that produced it - the traceability requirement this feature exists for.
The older analyze_share_of_voice() in competitor_intelligence/analyzer stays
untouched and keeps doing its own live-regex calculation for the GEO
report's "Share of tested AI answers" block; the two are never merged.

Sample gating reuses the existing AI Visibility minimum-query threshold
(MIN_QUERIES_FOR_VISIBILITY) - below it, share_of_voice is null, never a
fabricated percentage from a handful of responses. Competitors are always
operator-asserted (Competitor rows); Beacon never discovers or infers one.
"""

from datetime import date, datetime, time, timedelta

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models import (
    ENTITY_COMPETITOR,
    ENTITY_PROPERTY,
    AIShareOfVoiceSnapshot,
    AITopic,
    AIVisibilityPrompt,
    AIVisibilityQuery,
    Competitor,
    Mention,
    Property,
)
from app.services.ai_visibility.parsing import extract_sources
from app.services.ai_visibility.reference import (
    MIN_QUERIES_FOR_VISIBILITY,
    platform_label,
)
from app.services.ai_visibility.question_set import evaluate_must_contain
from app.services.reporting import compare_points, pct_point_change, previous_window

RESPONSE_EXCERPT_CHARS = 600

TOOLTIP_SOV = (
    "The share of AI-mentioned brands in tested responses that are this "
    "property: property mentions divided by property plus competitor "
    "mentions. Distinct from AI Visibility and Citation Share."
)
TOOLTIP_AI_VISIBILITY = (
    "How often this property appears in AI responses Beacon has tested, out "
    "of all eligible tested responses. Does not measure standing against "
    "competitors."
)
TOOLTIP_CITATION_SHARE = (
    "The share of cited sources across tested AI responses that point to "
    "this property's own domain. Not yet built; arrives with Citation Share "
    "reporting."
)


# --- window + filtered row fetch ---------------------------------------------


def _window(days: int, today: date) -> tuple[datetime, datetime]:
    end = datetime.combine(today, time.max)
    start = datetime.combine(today - timedelta(days=max(days, 1) - 1), time.min)
    return start, end


def _rows(
    db: Session,
    property_id: int,
    start: datetime | None,
    end: datetime | None,
    *,
    topic_id: int | None = None,
    platform: str | None = None,
    prompt_id: int | None = None,
    audience: str | None = None,
    location: str | None = None,
    intent: str | None = None,
    priority: str | None = None,
):
    """(AIVisibilityQuery, AIVisibilityPrompt|None) pairs in the window
    matching filters - one query, no N+1. Prompts join on property_id +
    prompt_text since AIVisibilityQuery has no prompt foreign key (existing
    pattern - see reporting_geo.matrix_cell_evidence)."""
    q = (
        db.query(AIVisibilityQuery, AIVisibilityPrompt)
        .outerjoin(
            AIVisibilityPrompt,
            and_(
                AIVisibilityPrompt.property_id == AIVisibilityQuery.property_id,
                AIVisibilityPrompt.prompt_text == AIVisibilityQuery.prompt_text,
            ),
        )
        .filter(AIVisibilityQuery.property_id == property_id)
    )
    if start is not None:
        q = q.filter(AIVisibilityQuery.executed_at >= start)
    if end is not None:
        q = q.filter(AIVisibilityQuery.executed_at <= end)
    if platform:
        q = q.filter(AIVisibilityQuery.platform == platform)
    if topic_id is not None:
        q = q.filter(AIVisibilityPrompt.topic_id == topic_id)
    if prompt_id is not None:
        q = q.filter(AIVisibilityPrompt.id == prompt_id)
    if audience:
        q = q.filter(AIVisibilityPrompt.audience == audience)
    if location:
        q = q.filter(AIVisibilityPrompt.location_market == location)
    if intent:
        q = q.filter(AIVisibilityPrompt.intent == intent)
    if priority:
        q = q.filter(AIVisibilityPrompt.priority == priority)
    return q.order_by(AIVisibilityQuery.executed_at.desc()).all()


def _mentions_for(
    db: Session, response_ids: list[int], competitor_id: int | None = None
) -> list[Mention]:
    if not response_ids:
        return []
    mq = db.query(Mention).filter(Mention.response_id.in_(response_ids))
    if competitor_id is not None:
        mq = mq.filter(
            or_(
                Mention.entity_type == ENTITY_PROPERTY,
                and_(
                    Mention.entity_type == ENTITY_COMPETITOR,
                    Mention.entity_id == competitor_id,
                ),
            )
        )
    return mq.all()


def _sov_calc(mentions: list[Mention], sample_size: int) -> dict:
    """Core formula: property mentions / (property + competitor mentions),
    sample-gated. Presence-counted (one Mention row per entity per
    response), matching the counting analyze_share_of_voice already uses."""
    prop_count = sum(1 for m in mentions if m.entity_type == ENTITY_PROPERTY)
    comp_counts: dict[int, int] = {}
    comp_names: dict[int, str] = {}
    for m in mentions:
        if m.entity_type == ENTITY_COMPETITOR:
            comp_counts[m.entity_id] = comp_counts.get(m.entity_id, 0) + 1
            comp_names[m.entity_id] = m.normalized_name
    total = prop_count + sum(comp_counts.values())
    sufficient = sample_size >= MIN_QUERIES_FOR_VISIBILITY

    def share(count: int) -> float | None:
        if not sufficient or total == 0:
            return None
        return round(count / total, 4)

    return {
        "property_mentions": prop_count,
        "competitor_mentions": comp_counts,
        "competitor_names": comp_names,
        "total_mentions": total,
        "sample_size": sample_size,
        "sufficient": sufficient,
        "share_of_voice": share(prop_count),
        "competitor_shares": {cid: share(c) for cid, c in comp_counts.items()},
    }


def _rank(prop_share: float | None, comp_shares: dict[int, float | None]) -> dict:
    """Competitive rank with explicit tie handling: entities with an equal
    share get the same rank number; the next distinct share skips ahead by
    the count of tied entities (competition-ranking convention: 1,2,2,4)."""
    if prop_share is None:
        return {"rank": None, "rank_of": None, "tied": False}
    entries = [("__property__", prop_share)] + [
        (cid, s) for cid, s in comp_shares.items() if s is not None
    ]
    entries.sort(key=lambda e: e[1], reverse=True)
    ranks: dict = {}
    current_rank = 0
    seen = 0
    prev_share = None
    for entity_id, share_val in entries:
        seen += 1
        if share_val != prev_share:
            current_rank = seen
            prev_share = share_val
        ranks[entity_id] = current_rank
    prop_rank = ranks.get("__property__")
    tied = sum(1 for _, s in entries if s == prop_share) > 1
    return {"rank": prop_rank, "rank_of": len(entries), "tied": tied}


def _calc_window(db, property_id, start, end, competitor_id=None, **filters) -> dict:
    pairs = _rows(db, property_id, start, end, **filters)
    ids = [q.id for q, _p in pairs]
    return _sov_calc(_mentions_for(db, ids, competitor_id=competitor_id), len(pairs))


# --- overview / trend / by-platform / by-topic --------------------------------


def _trend_granularity(days_span: int) -> str:
    if days_span <= 31:
        return "daily"
    if days_span <= 120:
        return "weekly"
    return "monthly"


def _bucket_key(dt: datetime, granularity: str) -> str:
    d = dt.date()
    if granularity == "daily":
        return d.isoformat()
    if granularity == "weekly":
        return (d - timedelta(days=d.weekday())).isoformat()
    return d.replace(day=1).isoformat()


def _trend(db, property_id, start, end, competitor_id=None, **filters) -> dict:
    days_span = (end.date() - start.date()).days + 1
    granularity = _trend_granularity(days_span)
    pairs = _rows(db, property_id, start, end, **filters)
    buckets: dict[str, list] = {}
    for q, _p in pairs:
        buckets.setdefault(_bucket_key(q.executed_at, granularity), []).append(q)

    points = []
    for key in sorted(buckets):
        qs = buckets[key]
        calc = _sov_calc(
            _mentions_for(db, [q.id for q in qs], competitor_id=competitor_id), len(qs)
        )
        points.append({
            "period": key,
            "share_of_voice": calc["share_of_voice"],
            "sample_size": calc["sample_size"],
            "sufficient": calc["sufficient"],
        })
    return {
        "granularity": granularity,
        "points": points,
        "note": (
            "Periods below the minimum tested-response sample show a null "
            "share rather than a misleading line."
        ),
    }


def _by_platform(db, property_id, start, end, **filters) -> list[dict]:
    pairs = _rows(db, property_id, start, end, **filters)
    platforms = sorted({q.platform for q, _p in pairs})
    rows = []
    for platform in platforms:
        ids = [q.id for q, _p in pairs if q.platform == platform]
        calc = _sov_calc(_mentions_for(db, ids), len(ids))
        top_competitor = None
        usable = {cid: s for cid, s in calc["competitor_shares"].items() if s is not None}
        if usable:
            top_id = max(usable, key=usable.get)
            top_competitor = {
                "id": top_id,
                "name": calc["competitor_names"][top_id],
                "share_of_voice": usable[top_id],
            }
        rank_info = _rank(calc["share_of_voice"], calc["competitor_shares"])
        rows.append({
            "platform": platform,
            "platform_label": platform_label(platform),
            "share_of_voice": calc["share_of_voice"],
            "sample_size": calc["sample_size"],
            "sufficient": calc["sufficient"],
            "top_competitor": top_competitor,
            "rank": rank_info["rank"],
            "rank_of": rank_info["rank_of"],
        })
    rows.sort(key=lambda r: (r["share_of_voice"] is None, -(r["share_of_voice"] or 0)))
    return rows


def _by_topic(db, property_id, prop_name, start, end, **filters) -> list[dict]:
    topics = (
        db.query(AITopic)
        .filter_by(property_id=property_id, status="active")
        .order_by(AITopic.topic_name)
        .all()
    )
    prev_start_d, prev_end_d = previous_window(start.date(), end.date())
    prev_start, prev_end = datetime.combine(prev_start_d, time.min), datetime.combine(
        prev_end_d, time.max
    )

    rows = []
    for topic in topics:
        calc = _calc_window(db, property_id, start, end, topic_id=topic.id, **filters)
        prev_calc = _calc_window(
            db, property_id, prev_start, prev_end, topic_id=topic.id, **filters
        )
        leader = None
        gap = None
        if calc["sufficient"]:
            candidates = [("__property__", calc["share_of_voice"], prop_name)] + [
                (cid, s, calc["competitor_names"][cid])
                for cid, s in calc["competitor_shares"].items()
                if s is not None
            ]
            candidates = [c for c in candidates if c[1] is not None]
            if candidates:
                leader_id, leader_share, leader_name = max(candidates, key=lambda c: c[1])
                is_property = leader_id == "__property__"
                leader = {
                    "is_property": is_property,
                    "name": leader_name,
                    "share_of_voice": leader_share,
                }
                if not is_property:
                    gap = round(leader_share - (calc["share_of_voice"] or 0), 4)
        trend_point_change = pct_point_change(
            calc["share_of_voice"], prev_calc["share_of_voice"]
        )
        trend_arrow = (
            None
            if trend_point_change is None
            else "up" if trend_point_change > 0 else "down" if trend_point_change < 0 else "flat"
        )
        rows.append({
            "topic_id": topic.id,
            "topic_name": topic.topic_name,
            "priority": topic.priority,
            "share_of_voice": calc["share_of_voice"],
            "sample_size": calc["sample_size"],
            "sufficient": calc["sufficient"],
            "leader": leader,
            "gap_to_leader": gap,
            "trend_arrow": trend_arrow,
            "trend_point_change": trend_point_change,
        })
    return rows


# --- top-level report ---------------------------------------------------------


def portfolio_average_sov(
    db: Session, property_id: int, days: int = 30, today: date | None = None
) -> dict:
    """Property-vs-portfolio-average comparison (Phase 18C), scoped to
    overall Share of Voice only (not per-topic, since AITopic names are not
    a shared cross-property taxonomy). Hard-gated off - never a fabricated
    benchmark - unless at least 2 OTHER active, competitor-tracked
    properties in the same company have a sufficient Share of Voice sample
    in this window."""
    today = today or date.today()
    prop = db.get(Property, property_id)
    if prop is None or prop.company_id is None:
        return {"available": False, "reason": "no_company"}

    siblings = (
        db.query(Property)
        .filter(
            Property.company_id == prop.company_id,
            Property.id != property_id,
            Property.is_active.is_(True),
        )
        .all()
    )
    start, end = _window(days, today)
    shares = []
    for sib in siblings:
        has_competitors = db.query(Competitor).filter_by(property_id=sib.id).first()
        if not has_competitors:
            continue
        calc = _calc_window(db, sib.id, start, end)
        if calc["sufficient"] and calc["share_of_voice"] is not None:
            shares.append(calc["share_of_voice"])

    if len(shares) < 2:
        return {
            "available": False,
            "reason": "insufficient_portfolio_data",
            "property_count": len(shares),
        }
    return {
        "available": True,
        "reason": None,
        "average_share_of_voice": round(sum(shares) / len(shares), 4),
        "property_count": len(shares),
    }


def build_sov_report(
    db: Session,
    property_id: int | None,
    days: int = 30,
    compare: bool = False,
    *,
    topic_id: int | None = None,
    platform: str | None = None,
    prompt_id: int | None = None,
    competitor_id: int | None = None,
    audience: str | None = None,
    location: str | None = None,
    intent: str | None = None,
    priority: str | None = None,
    today: date | None = None,
) -> dict:
    today = today or date.today()
    if property_id is None:
        return {
            "scope_required": True,
            "message": "Select a single property to view its AI Share of Voice report.",
        }
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")

    competitors = (
        db.query(Competitor)
        .filter_by(property_id=property_id)
        .order_by(Competitor.name)
        .all()
    )
    if not competitors:
        return {
            "scope_required": False,
            "property_id": property_id,
            "property_name": prop.name,
            "has_competitors": False,
            "message": (
                "No competitors are tracked for this property yet. Add the "
                "competitors you want compared before Share of Voice can be "
                "computed - Beacon never guesses them."
            ),
            "tooltips": {
                "ai_share_of_voice": TOOLTIP_SOV,
                "ai_visibility": TOOLTIP_AI_VISIBILITY,
                "citation_share": TOOLTIP_CITATION_SHARE,
            },
        }

    if competitor_id is not None and not any(c.id == competitor_id for c in competitors):
        raise ValueError("Competitor not found for this property.")

    filters = dict(
        topic_id=topic_id, platform=platform, prompt_id=prompt_id,
        audience=audience, location=location, intent=intent, priority=priority,
    )
    start, end = _window(days, today)
    calc = _calc_window(db, property_id, start, end, competitor_id=competitor_id, **filters)
    rank_info = _rank(calc["share_of_voice"], calc["competitor_shares"])

    overview = {
        "share_of_voice": calc["share_of_voice"],
        "property_mentions": calc["property_mentions"],
        "competitor_mentions": sum(calc["competitor_mentions"].values()),
        "total_mentions": calc["total_mentions"],
        "eligible_responses": calc["sample_size"],
        "sample_size": calc["sample_size"],
        "sufficient": calc["sufficient"],
        "rank": rank_info["rank"],
        "rank_of": rank_info["rank_of"],
        "tied": rank_info["tied"],
        "comparison": None,
    }
    if compare:
        prev_start_d, prev_end_d = previous_window(start.date(), end.date())
        prev_start, prev_end = (
            datetime.combine(prev_start_d, time.min),
            datetime.combine(prev_end_d, time.max),
        )
        prev_calc = _calc_window(
            db, property_id, prev_start, prev_end, competitor_id=competitor_id, **filters
        )
        overview["comparison"] = compare_points(
            calc["share_of_voice"], prev_calc["share_of_voice"]
        )

    return {
        "scope_required": False,
        "property_id": property_id,
        "property_name": prop.name,
        "has_competitors": True,
        "generated_on": today.isoformat(),
        "window": {
            "start": start.date().isoformat(),
            "end": end.date().isoformat(),
            "days": days,
        },
        "overview": overview,
        "trend": _trend(db, property_id, start, end, competitor_id=competitor_id, **filters),
        "by_platform": _by_platform(db, property_id, start, end, **{
            k: v for k, v in filters.items() if k != "platform"
        }),
        "by_topic": _by_topic(db, property_id, prop.name, start, end, **{
            k: v for k, v in filters.items() if k != "topic_id"
        }),
        "portfolio_average": portfolio_average_sov(db, property_id, days, today),
        "tooltips": {
            "ai_share_of_voice": TOOLTIP_SOV,
            "ai_visibility": TOOLTIP_AI_VISIBILITY,
            "citation_share": TOOLTIP_CITATION_SHARE,
        },
    }


# --- drilldown: topic -> prompt -> response evidence ---------------------------


def sov_topic_drilldown(
    db: Session, property_id: int, topic_id: int, days: int = 30,
    *, platform: str | None = None, today: date | None = None,
) -> dict:
    today = today or date.today()
    topic = db.get(AITopic, topic_id)
    if topic is None or topic.property_id != property_id:
        raise ValueError("Topic not found for this property.")
    prop = db.get(Property, property_id)
    start, end = _window(days, today)

    prompts = (
        db.query(AIVisibilityPrompt)
        .filter_by(property_id=property_id, topic_id=topic_id)
        .order_by(AIVisibilityPrompt.id)
        .all()
    )
    rows = []
    for prompt in prompts:
        calc = _calc_window(
            db, property_id, start, end, prompt_id=prompt.id, platform=platform
        )
        pairs = _rows(db, property_id, start, end, prompt_id=prompt.id, platform=platform)
        leader = None
        if calc["sufficient"]:
            candidates = [("__property__", calc["share_of_voice"], prop.name)] + [
                (cid, s, calc["competitor_names"][cid])
                for cid, s in calc["competitor_shares"].items() if s is not None
            ]
            candidates = [c for c in candidates if c[1] is not None]
            if candidates:
                _lid, lshare, lname = max(candidates, key=lambda c: c[1])
                leader = {"name": lname, "share_of_voice": lshare}
        rows.append({
            "prompt_id": prompt.id,
            "prompt_text": prompt.prompt_text,
            "platform": prompt.platform,
            "share_of_voice": calc["share_of_voice"],
            "sample_size": calc["sample_size"],
            "sufficient": calc["sufficient"],
            "mentioned": calc["property_mentions"] > 0,
            "leader": leader,
            "runs_in_window": len(pairs),
        })
    return {
        "topic": {
            "id": topic.id, "topic_name": topic.topic_name,
            "description": topic.description, "priority": topic.priority,
        },
        "window": {"start": start.date().isoformat(), "end": end.date().isoformat(), "days": days},
        "prompts": rows,
    }


def sov_prompt_drilldown(
    db: Session, property_id: int, prompt_id: int, days: int = 30,
    *, today: date | None = None,
) -> dict:
    today = today or date.today()
    prompt = db.get(AIVisibilityPrompt, prompt_id)
    if prompt is None or prompt.property_id != property_id:
        raise ValueError("Prompt not found for this property.")
    start, end = _window(days, today)
    pairs = _rows(db, property_id, start, end, prompt_id=prompt_id)

    responses = []
    for q, _p in pairs:
        mentions = _mentions_for(db, [q.id])
        calc = _sov_calc(mentions, 1)
        responses.append({
            "response_id": q.id,
            "platform": q.platform,
            "platform_label": platform_label(q.platform),
            "run_date": q.executed_at.date().isoformat(),
            "mentioned": any(m.entity_type == ENTITY_PROPERTY for m in mentions),
            "competitors_mentioned": [
                calc["competitor_names"][cid] for cid in calc["competitor_mentions"]
            ],
        })
    return {
        "prompt": {
            "id": prompt.id, "prompt_text": prompt.prompt_text,
            "platform": prompt.platform, "topic_id": prompt.topic_id,
        },
        "window": {"start": start.date().isoformat(), "end": end.date().isoformat(), "days": days},
        "responses": responses,
    }


def sov_response_evidence(db: Session, property_id: int, response_id: int) -> dict:
    """Response-level evidence: mirrors reporting_geo.matrix_cell_evidence -
    the full stored response plus every Mention row Beacon deterministically
    attributed to it, so the KPI figure can be walked all the way down to
    the text that produced it."""
    q = db.get(AIVisibilityQuery, response_id)
    if q is None or q.property_id != property_id:
        raise ValueError("Response not found for this property.")
    prop = db.get(Property, property_id)
    mentions = _mentions_for(db, [response_id])
    cites = sorted({d for d in (q.sources_cited or []) if d}) or extract_sources(
        q.raw_response_text
    )
    excerpt = q.raw_response_text.strip()
    truncated = len(excerpt) > RESPONSE_EXCERPT_CHARS

    prompt_row = (
        db.query(AIVisibilityPrompt)
        .filter(
            AIVisibilityPrompt.property_id == property_id,
            AIVisibilityPrompt.prompt_text == q.prompt_text,
        )
        .first()
    )
    required = evaluate_must_contain(
        q.raw_response_text, prompt_row.must_contain if prompt_row else None
    )

    return {
        "response_id": q.id,
        "prompt": q.prompt_text,
        "platform": q.platform,
        "platform_label": platform_label(q.platform),
        "run_date": q.executed_at.date().isoformat(),
        "execution_status": q.execution_status,
        "model_metadata": q.model_metadata,
        "response_excerpt": excerpt[:RESPONSE_EXCERPT_CHARS] + ("..." if truncated else ""),
        "cited_domains": cites,
        "mentions": [
            {
                "entity_type": m.entity_type,
                "entity_id": m.entity_id,
                "normalized_name": m.normalized_name,
                "raw_matched_text": m.raw_matched_text,
                "match_count": m.match_count,
                "position": m.position,
                "confidence": m.confidence,
            }
            for m in mentions
        ],
        "required_components": required,
        "owning_url": prompt_row.owning_url if prompt_row else None,
        "topic_id": prompt_row.topic_id if prompt_row else None,
    }


# --- competitive ranking + winners/losers + KPI card ---------------------------


def competitive_ranking(
    db: Session, property_id: int, days: int = 30,
    *, topic_id: int | None = None, platform: str | None = None,
    today: date | None = None,
) -> dict:
    today = today or date.today()
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    competitors = (
        db.query(Competitor).filter_by(property_id=property_id).order_by(Competitor.name).all()
    )
    if not competitors:
        return {"has_competitors": False, "entities": []}

    start, end = _window(days, today)
    calc = _calc_window(db, property_id, start, end, topic_id=topic_id, platform=platform)

    entities = [{
        "id": None, "name": prop.name, "is_property": True,
        "share_of_voice": calc["share_of_voice"], "mentions": calc["property_mentions"],
    }]
    for c in competitors:
        entities.append({
            "id": c.id, "name": c.name, "is_property": False,
            "share_of_voice": calc["competitor_shares"].get(c.id),
            "mentions": calc["competitor_mentions"].get(c.id, 0),
        })

    ranked = sorted(
        (e for e in entities if e["share_of_voice"] is not None),
        key=lambda e: e["share_of_voice"], reverse=True,
    )
    unranked = [e for e in entities if e["share_of_voice"] is None]
    rank, seen, prev = 0, 0, None
    for e in ranked:
        seen += 1
        if e["share_of_voice"] != prev:
            rank = seen
            prev = e["share_of_voice"]
        e["rank"] = rank
    for e in unranked:
        e["rank"] = None

    return {
        "has_competitors": True,
        "sufficient": calc["sufficient"],
        "sample_size": calc["sample_size"],
        "entities": ranked + unranked,
    }


def winners_losers(db: Session, property_id: int, days: int = 30, today: date | None = None) -> dict:
    """Biggest Share of Voice gain/loss (property, current vs. previous
    equal-length window), fastest-growing competitor, and the largest
    competitive gap - computed live from the same Mention-backed windows as
    the rest of the report, so this is always accurate regardless of
    whether a scheduled snapshot has run. Returns an explicit
    insufficient-data state, never a fabricated winner, when either window
    lacks enough tested responses."""
    today = today or date.today()
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    competitors = (
        db.query(Competitor).filter_by(property_id=property_id).order_by(Competitor.name).all()
    )
    empty = {
        "sufficient": False,
        "biggest_gain": None, "biggest_loss": None,
        "fastest_growing_competitor": None, "largest_competitive_gap": None,
    }
    if not competitors:
        return {**empty, "message": "No competitors are tracked for this property yet."}

    start, end = _window(days, today)
    prev_start_d, prev_end_d = previous_window(start.date(), end.date())
    prev_start, prev_end = (
        datetime.combine(prev_start_d, time.min),
        datetime.combine(prev_end_d, time.max),
    )
    cur_calc = _calc_window(db, property_id, start, end)
    prev_calc = _calc_window(db, property_id, prev_start, prev_end)

    if not cur_calc["sufficient"] or not prev_calc["sufficient"]:
        return {
            **empty,
            "message": (
                "Sample size is below the minimum tested-response threshold "
                "in the current or previous period, so winners and losers "
                "are not shown."
            ),
        }

    prop_change = pct_point_change(cur_calc["share_of_voice"], prev_calc["share_of_voice"])
    fastest_growing = None
    largest_gap = None
    for c in competitors:
        cur_s = cur_calc["competitor_shares"].get(c.id)
        prev_s = prev_calc["competitor_shares"].get(c.id)
        change = pct_point_change(cur_s, prev_s)
        if change is not None and (
            fastest_growing is None or change > fastest_growing["point_change"]
        ):
            fastest_growing = {
                "id": c.id, "name": c.name, "point_change": change,
                "current_share": cur_s, "previous_share": prev_s,
            }
        if cur_s is not None and cur_calc["share_of_voice"] is not None:
            gap = round(cur_s - cur_calc["share_of_voice"], 4)
            if gap > 0 and (largest_gap is None or gap > largest_gap["gap"]):
                largest_gap = {
                    "id": c.id, "name": c.name, "gap": gap,
                    "competitor_share": cur_s, "property_share": cur_calc["share_of_voice"],
                }

    return {
        "sufficient": True,
        "biggest_gain": (
            {"entity": "property", "point_change": prop_change}
            if prop_change is not None and prop_change > 0 else None
        ),
        "biggest_loss": (
            {"entity": "property", "point_change": prop_change}
            if prop_change is not None and prop_change < 0 else None
        ),
        "fastest_growing_competitor": fastest_growing,
        "largest_competitive_gap": largest_gap,
    }


def explain_sov_change(
    db: Session, property_id: int, days: int = 30, today: date | None = None
) -> dict | None:
    """Deterministic decomposition of an aggregate Share of Voice change, for
    Nora's Observation/Diagnosis/Hypothesis gate (Phase 18C): finds the
    single topic whose own change is large enough to plausibly account for
    the aggregate move, so Nora can offer a Supported Diagnosis instead of
    guessing. Returns None (no diagnosis - Nora must stay at Observation/
    Hypothesis) when either period lacks enough data, no topics are
    configured, the aggregate did not move, or no single topic's change
    covers at least half of the aggregate change in the same direction.
    Beacon would rather say "not enough data" than point at the wrong
    contributor."""
    today = today or date.today()
    prop = db.get(Property, property_id)
    if prop is None:
        return None

    start, end = _window(days, today)
    prev_start_d, prev_end_d = previous_window(start.date(), end.date())
    prev_start, prev_end = (
        datetime.combine(prev_start_d, time.min),
        datetime.combine(prev_end_d, time.max),
    )
    cur = _calc_window(db, property_id, start, end)
    prev = _calc_window(db, property_id, prev_start, prev_end)
    if not cur["sufficient"] or not prev["sufficient"]:
        return None

    aggregate_change = pct_point_change(cur["share_of_voice"], prev["share_of_voice"])
    if not aggregate_change:
        return None

    topics = (
        db.query(AITopic).filter_by(property_id=property_id, status="active").all()
    )
    if not topics:
        return None

    best = None
    for topic in topics:
        t_cur = _calc_window(db, property_id, start, end, topic_id=topic.id)
        t_prev = _calc_window(db, property_id, prev_start, prev_end, topic_id=topic.id)
        if not t_cur["sufficient"] or not t_prev["sufficient"]:
            continue
        change = pct_point_change(t_cur["share_of_voice"], t_prev["share_of_voice"])
        if change is None:
            continue
        same_direction = (change > 0) == (aggregate_change > 0)
        if not same_direction or abs(change) < abs(aggregate_change) * 0.5:
            continue
        if best is None or abs(change) > abs(best["point_change"]):
            best = {
                "topic_id": topic.id,
                "topic_name": topic.topic_name,
                "point_change": change,
            }
    if best is None:
        return None
    return {**best, "aggregate_point_change": aggregate_change}


def sov_kpi_card(db: Session, property_id: int, days: int = 30, today: date | None = None) -> dict:
    today = today or date.today()
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    competitors = db.query(Competitor).filter_by(property_id=property_id).all()
    if not competitors:
        return {
            "has_competitors": False, "share_of_voice": None,
            "message": "Add competitors to compute Share of Voice.",
        }

    start, end = _window(days, today)
    calc = _calc_window(db, property_id, start, end)
    rank_info = _rank(calc["share_of_voice"], calc["competitor_shares"])

    prev_start_d, prev_end_d = previous_window(start.date(), end.date())
    prev_start, prev_end = (
        datetime.combine(prev_start_d, time.min),
        datetime.combine(prev_end_d, time.max),
    )
    prev_calc = _calc_window(db, property_id, prev_start, prev_end)

    rank_label = (
        f"#{rank_info['rank']} of {rank_info['rank_of']}"
        if rank_info["rank"] is not None else None
    )

    return {
        "has_competitors": True,
        "share_of_voice": calc["share_of_voice"],
        "sufficient": calc["sufficient"],
        "sample_size": calc["sample_size"],
        "rank": rank_info["rank"],
        "rank_of": rank_info["rank_of"],
        "rank_label": rank_label,
        "tied": rank_info["tied"],
        "comparison": compare_points(calc["share_of_voice"], prev_calc["share_of_voice"]),
    }


# --- historical snapshots -------------------------------------------------------


def snapshot_sov(
    db: Session, property_id: int, days: int = 30, today: date | None = None
) -> list[AIShareOfVoiceSnapshot]:
    """Writes one AIShareOfVoiceSnapshot per (topic, all-topics) and (all-
    topics, platform) scope for the trailing `days` window ending today.
    Upserts (delete-then-insert on the same property/period) so repeated
    scheduled calls the same day stay idempotent. Called alongside
    ai_visibility/schedule.py's snapshot_score() so AI Visibility and Share
    of Voice history accrue together. This is separate from the live
    calculations above (which read Mention rows directly) - the snapshot
    table exists for rank/share history over time without re-scanning the
    full response history on every read."""
    today = today or date.today()
    prop = db.get(Property, property_id)
    if prop is None:
        return []
    competitors = db.query(Competitor).filter_by(property_id=property_id).all()
    if not competitors:
        return []

    start, end = _window(days, today)
    period_start, period_end = start.date(), end.date()

    db.query(AIShareOfVoiceSnapshot).filter(
        AIShareOfVoiceSnapshot.property_id == property_id,
        AIShareOfVoiceSnapshot.period_start == period_start,
        AIShareOfVoiceSnapshot.period_end == period_end,
    ).delete()

    topics = db.query(AITopic).filter_by(property_id=property_id).all()
    all_pairs = _rows(db, property_id, start, end)
    platforms = sorted({q.platform for q, _p in all_pairs})
    scopes: list[tuple[int | None, str | None]] = [(None, None)]
    scopes += [(t.id, None) for t in topics]
    scopes += [(None, p) for p in platforms]

    rows = []
    for topic_id, platform in scopes:
        calc = _calc_window(db, property_id, start, end, topic_id=topic_id, platform=platform)
        rank_info = _rank(calc["share_of_voice"], calc["competitor_shares"])
        row = AIShareOfVoiceSnapshot(
            property_id=property_id,
            topic_id=topic_id,
            platform=platform,
            period_start=period_start,
            period_end=period_end,
            captured_at=datetime.combine(today, time.min),
            property_mentions=calc["property_mentions"],
            competitor_mentions=sum(calc["competitor_mentions"].values()),
            sample_size=calc["sample_size"],
            sufficient=calc["sufficient"],
            share_of_voice=calc["share_of_voice"],
            rank=rank_info["rank"],
            rank_of=rank_info["rank_of"],
        )
        db.add(row)
        rows.append(row)
    db.commit()
    return rows


# --- RAG chunk text --------------------------------------------------------------


def share_of_voice_summary_text(db: Session, property_id: int) -> str | None:
    """Deterministic Share of Voice summary for the RAG index, or None when
    there is nothing real to say (no competitors, or sample below the
    minimum). Feeds Nora's retrieval so she can ground Share of Voice
    answers without a bespoke query path."""
    prop = db.get(Property, property_id)
    if prop is None:
        return None
    report = build_sov_report(db, property_id, 30, compare=True)
    if report.get("scope_required") or not report.get("has_competitors"):
        return None
    ov = report["overview"]
    if not ov["sufficient"] or ov["share_of_voice"] is None:
        return None

    lines = [
        f"AI Share of Voice summary for {prop.name} "
        f"({report['window']['start']} to {report['window']['end']}).",
        f"Share of Voice is {round(ov['share_of_voice'] * 100)}% "
        f"({ov['property_mentions']} of {ov['total_mentions']} mentions across "
        f"{ov['eligible_responses']} tested responses).",
    ]
    if ov["rank"] is not None:
        lines.append(
            f"Competitive rank: #{ov['rank']} of {ov['rank_of']}"
            f"{' (tied)' if ov['tied'] else ''}."
        )
    comparison = ov.get("comparison")
    if comparison and comparison.get("point_change") is not None:
        pts = round(comparison["point_change"] * 100)
        lines.append(
            f"Change vs the previous period: {'+' if pts >= 0 else ''}{pts} "
            "percentage points."
        )

    topic_rows = [t for t in report["by_topic"] if t["sufficient"] and t["share_of_voice"] is not None]
    if topic_rows:
        lines.append("By topic:")
        for t in sorted(topic_rows, key=lambda t: t["share_of_voice"])[:5]:
            leader_note = ""
            if t["leader"] and not t["leader"]["is_property"] and t["gap_to_leader"] is not None:
                leader_note = (
                    f", led by {t['leader']['name']} "
                    f"(gap {round(t['gap_to_leader'] * 100)} pts)"
                )
            lines.append(f"- {t['topic_name']}: {round(t['share_of_voice'] * 100)}%{leader_note}.")

    plat_rows = [p for p in report["by_platform"] if p["sufficient"] and p["share_of_voice"] is not None]
    if plat_rows:
        lines.append(
            "By platform: "
            + "; ".join(
                f"{p['platform_label']} {round(p['share_of_voice'] * 100)}%"
                for p in plat_rows
            )
            + "."
        )

    return "\n".join(lines)
