"""Observatory metrics (Phase 19, slice 3). Every formula is inspectable
(METRIC_DEFINITIONS), every value carries numerator/denominator, a data
label, and a DataState; below the minimum sample the value is None, never
a fabricated 0. Reads rollups only (ai_visibility_daily,
ai_cluster_visibility_daily) plus ai_citations for source influence."""

from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    AICitation,
    AIClusterVisibilityDaily,
    Competitor,
    Property,
    AIPromptAssignment,
    AIPromptCluster,
    AIPropertyObservation,
    AIVisibilityDaily,
)
from app.models.ai_observations import PLATFORM_ALL
from app.services.ai_visibility.reference import MIN_QUERIES_FOR_VISIBILITY
from app.services.observatory import LABEL_MEASURED, LABEL_MODELED
from app.services.observatory.citations import competitor_domains_for, owned_domains_for
from app.services.reporting import DataState, compare_points, previous_window, rate

PRIORITY_CLUSTER_MIN_IMPORTANCE = 3

METRIC_DEFINITIONS = {
    "ai_visibility": {
        "label": "AI Visibility",
        "formula": "responses where the property appears / eligible monitored responses",
        "data_label": LABEL_MEASURED,
        "note": "Presence only; says nothing about competitors.",
    },
    "citation_rate": {
        "label": "Citation Rate",
        "formula": "responses citing the property's owned domain / eligible responses",
        "data_label": LABEL_MEASURED,
    },
    "recommendation_rate": {
        "label": "Recommendation Rate",
        "formula": "responses where the property is classified as recommended / eligible responses",
        "data_label": LABEL_MODELED,
        "note": "Rule v1: named among the first three entities, or a non-negated recommendation cue near the mention.",
    },
    "citation_share": {
        "label": "Citation Share",
        "formula": "owned-domain citations / (owned + tracked-competitor citations)",
        "data_label": LABEL_MEASURED,
    },
    "share_of_voice": {
        "label": "Share of Voice",
        "formula": "property mention responses / (property mention responses + tracked-competitor mentions)",
        "data_label": LABEL_MEASURED,
        "note": "Same definition as the Phase 18 Share of Voice report.",
    },
    "prompt_coverage": {
        "label": "Prompt Coverage",
        "formula": "priority prompt clusters where the property appeared at least once / priority clusters assigned",
        "data_label": LABEL_MEASURED,
    },
    "competitor_win_rate": {
        "label": "Competitor Win Rate",
        "formula": "responses where a tracked competitor appears and the property does not / eligible responses",
        "data_label": LABEL_MEASURED,
    },
    "source_influence": {
        "label": "Source Influence",
        "formula": "citations of a domain / all citations in eligible responses",
        "data_label": LABEL_MEASURED,
    },
}


def _window(days: int, today: date) -> tuple[date, date]:
    return today - timedelta(days=max(days, 1) - 1), today


def _sum_rollups(db: Session, property_id: int, start: date, end: date, platform: str) -> dict:
    cols = [
        "eligible_count", "mentioned_count", "cited_count", "recommended_count",
        "owned_citation_count", "tracked_citation_count", "total_citation_count",
        "property_mention_responses", "competitor_mention_count", "competitor_win_count",
        "sentiment_pos", "sentiment_neu", "sentiment_neg", "runs_count",
    ]
    row = (
        db.query(*[func.coalesce(func.sum(getattr(AIVisibilityDaily, c)), 0) for c in cols])
        .filter(
            AIVisibilityDaily.property_id == property_id,
            AIVisibilityDaily.platform == platform,
            AIVisibilityDaily.day >= start,
            AIVisibilityDaily.day <= end,
        )
        .one()
    )
    return dict(zip(cols, [int(v) for v in row]))


def _metric(key: str, numerator: int, denominator: int, minimum: int = MIN_QUERIES_FOR_VISIBILITY) -> dict:
    r = rate(numerator, denominator, minimum)
    d = METRIC_DEFINITIONS[key]
    return {
        "key": key, "label": d["label"], "value": r["value"], "numerator": r["numerator"],
        "denominator": r["denominator"], "minimum_sample": r["minimum_sample"], "state": r["state"],
        "formula": d["formula"], "data_label": d["data_label"], "note": d.get("note"),
    }


def share_of_voice_metric(property_mentions: int, competitor_mentions: int, sample_size: int) -> dict:
    """Phase 18 semantics exactly: property / (property + competitor
    mentions), gated on the RESPONSE sample (not the mention total), null
    when nobody was mentioned."""
    total = property_mentions + competitor_mentions
    sufficient = sample_size >= MIN_QUERIES_FOR_VISIBILITY
    d = METRIC_DEFINITIONS["share_of_voice"]
    return {
        "key": "share_of_voice", "label": d["label"],
        "value": round(property_mentions / total, 4) if sufficient and total else None,
        "numerator": property_mentions, "denominator": total, "sample_size": sample_size,
        "minimum_sample": MIN_QUERIES_FOR_VISIBILITY,
        "state": (DataState.COMPLETE if sufficient else DataState.INSUFFICIENT_SAMPLE).value,
        "formula": d["formula"], "data_label": d["data_label"], "note": d.get("note"),
    }


def metrics_for_window(db: Session, property_id: int, start: date, end: date, platform: str = PLATFORM_ALL) -> dict:
    s = _sum_rollups(db, property_id, start, end, platform)
    eligible = s["eligible_count"]
    return {
        "ai_visibility": _metric("ai_visibility", s["mentioned_count"], eligible),
        "citation_rate": _metric("citation_rate", s["cited_count"], eligible),
        "recommendation_rate": _metric("recommendation_rate", s["recommended_count"], eligible),
        "citation_share": _metric("citation_share", s["owned_citation_count"], s["tracked_citation_count"], 1),
        "share_of_voice": share_of_voice_metric(
            s["property_mention_responses"], s["competitor_mention_count"], eligible
        ),
        "competitor_win_rate": _metric("competitor_win_rate", s["competitor_win_count"], eligible),
        "counts": s,
    }


def prompt_coverage(db: Session, property_id: int, start: date, end: date) -> dict:
    assigned = (
        db.query(AIPromptAssignment.cluster_id)
        .join(AIPromptCluster, AIPromptCluster.id == AIPromptAssignment.cluster_id)
        .filter(
            AIPromptAssignment.property_id == property_id,
            AIPromptAssignment.active.is_(True),
            AIPromptCluster.importance >= PRIORITY_CLUSTER_MIN_IMPORTANCE,
        )
        .all()
    )
    priority_ids = {cid for (cid,) in assigned if cid is not None}
    covered = set()
    if priority_ids:
        rows = (
            db.query(AIClusterVisibilityDaily.cluster_id, func.sum(AIClusterVisibilityDaily.mentioned_count))
            .filter(
                AIClusterVisibilityDaily.property_id == property_id,
                AIClusterVisibilityDaily.cluster_id.in_(priority_ids),
                AIClusterVisibilityDaily.day >= start,
                AIClusterVisibilityDaily.day <= end,
            )
            .group_by(AIClusterVisibilityDaily.cluster_id)
            .all()
        )
        covered = {cid for cid, mentioned in rows if (mentioned or 0) > 0}
    out = _metric("prompt_coverage", len(covered), len(priority_ids), 1)
    out["covered_cluster_ids"] = sorted(covered)
    out["priority_cluster_ids"] = sorted(priority_ids)
    return out


def source_influence(db: Session, property_id: int, start: date, end: date, limit: int = 25) -> dict:
    """Domains cited across the property's eligible responses in the window,
    with share of all citations. Reads ai_citations joined through the
    observations (so a market response counts for every property scored)."""
    response_ids = [
        rid for (rid,) in db.query(AIPropertyObservation.response_id)
        .filter(
            AIPropertyObservation.property_id == property_id,
            AIPropertyObservation.eligible.is_(True),
            AIPropertyObservation.observed_at >= datetime.combine(start, datetime.min.time()),
            AIPropertyObservation.observed_at < datetime.combine(end + timedelta(days=1), datetime.min.time()),
        )
        .distinct()
        .all()
    ]
    if not response_ids:
        return {"total_citations": 0, "domains": [], "data_label": LABEL_MEASURED,
                "formula": METRIC_DEFINITIONS["source_influence"]["formula"]}
    rows = (
        db.query(AICitation.domain, AICitation.source_type, func.count(AICitation.id),
                 func.count(func.distinct(AICitation.response_id)))
        .filter(AICitation.response_id.in_(response_ids))
        .group_by(AICitation.domain, AICitation.source_type)
        .order_by(func.count(AICitation.id).desc(), AICitation.domain)
        .all()
    )
    # A shared market answer was classified against every property it scored,
    # so "owned" there can mean another property's site. Relabel for the
    # property being viewed: its own domain is owned, its tracked
    # competitors' domains are competitor, any other scored property's site
    # is property_site.
    prop = db.get(Property, property_id)
    owned = owned_domains_for(prop) if prop else set()
    comps = db.query(Competitor).filter_by(property_id=property_id).all()
    comp_domains = competitor_domains_for(comps)

    def relabel(domain: str, stored: str | None) -> str | None:
        if any(domain == o or domain.endswith("." + o) for o in owned):
            return "owned"
        if any(domain == c or domain.endswith("." + c) for c in comp_domains):
            return "competitor"
        return "property_site" if stored in ("owned", "competitor") else stored

    merged: dict[tuple[str, str | None], list[int]] = {}
    for d, st, c, r in rows:
        key = (d, relabel(d, st))
        agg = merged.setdefault(key, [0, 0])
        agg[0] += c
        agg[1] += r
    ordered = sorted(merged.items(), key=lambda kv: (-kv[1][0], kv[0][0]))
    total = sum(c for _, (c, _) in ordered)
    domains = [
        {"domain": d, "source_type": st, "citations": c, "responses": r,
         "share": round(c / total, 4) if total else None}
        for (d, st), (c, r) in ordered[:limit]
    ]
    return {"total_citations": total, "domains": domains, "data_label": LABEL_MEASURED,
            "formula": METRIC_DEFINITIONS["source_influence"]["formula"]}


def trend(db: Session, property_id: int, metric: str, days: int, today: date, platform: str = PLATFORM_ALL) -> dict:
    """Current vs previous equal window (percentage points) plus a daily
    series; days below the minimum sample carry a null value."""
    start, end = _window(days, today)
    prev_start, prev_end = previous_window(start, end)
    current = metrics_for_window(db, property_id, start, end, platform)
    previous = metrics_for_window(db, property_id, prev_start, prev_end, platform)
    if metric == "prompt_coverage":
        cur_m, prev_m = prompt_coverage(db, property_id, start, end), prompt_coverage(db, property_id, prev_start, prev_end)
    else:
        cur_m, prev_m = current.get(metric), previous.get(metric)
    if cur_m is None:
        raise ValueError(f"Unknown metric '{metric}'.")

    num_col, den_col = {
        "ai_visibility": ("mentioned_count", "eligible_count"),
        "citation_rate": ("cited_count", "eligible_count"),
        "recommendation_rate": ("recommended_count", "eligible_count"),
        "competitor_win_rate": ("competitor_win_count", "eligible_count"),
        "citation_share": ("owned_citation_count", "tracked_citation_count"),
        "share_of_voice": ("property_mention_responses", None),
    }.get(metric, (None, None))
    series = []
    if num_col:
        rows = (
            db.query(AIVisibilityDaily)
            .filter(AIVisibilityDaily.property_id == property_id, AIVisibilityDaily.platform == platform,
                    AIVisibilityDaily.day >= start, AIVisibilityDaily.day <= end)
            .order_by(AIVisibilityDaily.day)
            .all()
        )
        for r in rows:
            num = getattr(r, num_col)
            if metric == "share_of_voice":
                pt = share_of_voice_metric(num, r.competitor_mention_count, r.eligible_count)
            else:
                pt = rate(num, getattr(r, den_col), MIN_QUERIES_FOR_VISIBILITY if metric != "citation_share" else 1)
            series.append({"day": r.day.isoformat(), "value": pt["value"], "numerator": num,
                           "denominator": pt["denominator"], "sufficient": pt["value"] is not None})
    return {
        "metric": metric,
        "label": METRIC_DEFINITIONS[metric]["label"],
        "data_label": METRIC_DEFINITIONS[metric]["data_label"],
        "window": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "previous_window": {"start": prev_start.isoformat(), "end": prev_end.isoformat()},
        "current": cur_m,
        "previous": prev_m,
        "comparison": compare_points(cur_m["value"], prev_m["value"]),
        "series": series,
        "note": "Days below the minimum sample show a null value rather than a misleading point.",
    }
