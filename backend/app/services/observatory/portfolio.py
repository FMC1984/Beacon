"""Portfolio intelligence (Phase 19, slice 6).

Across a company (or the unassigned properties, or everything): each
property's Observatory metrics, averages over ONLY the properties with a
sufficient sample (unavailable with fewer than two), questions where several
properties have open content gaps, and the domains AI answers cite most
across the portfolio. Patterns are stated as counts, never as causes.
"""

from collections import Counter
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import AICitation, AIContentGap, AIPropertyObservation, Property
from app.services.metrics import _resolve_scope
from app.services.observatory import LABEL_MEASURED, LABEL_MODELED, utc_today
from app.services.observatory.metrics import metrics_for_window

MIN_PROPERTIES_FOR_AVERAGE = 2
MIN_PROPERTIES_FOR_PATTERN = 2


def portfolio_summary(
    db: Session, company_id: int | None = None, unassigned: bool = False, days: int = 30, today: date | None = None
) -> dict:
    today = today or utc_today()
    start, end = today - timedelta(days=days - 1), today
    ids = _resolve_scope(db, None, company_id, unassigned)
    q = db.query(Property).filter(Property.is_active.is_(True))
    if ids is not None:
        q = q.filter(Property.id.in_(ids or [-1]))
    props = q.order_by(Property.name).all()

    rows = []
    for p in props:
        m = metrics_for_window(db, p.id, start, end)
        rows.append({
            "property_id": p.id, "name": p.name, "market_id": p.market_id,
            "eligible_responses": m["counts"]["eligible_count"],
            "ai_visibility": m["ai_visibility"]["value"], "citation_rate": m["citation_rate"]["value"],
            "share_of_voice": m["share_of_voice"]["value"], "recommendation_rate": m["recommendation_rate"]["value"],
        })

    def average(key: str) -> dict:
        vals = [r[key] for r in rows if r[key] is not None]
        if len(vals) < MIN_PROPERTIES_FOR_AVERAGE:
            return {"value": None, "properties": len(vals), "label": LABEL_MEASURED,
                    "note": f"Needs at least {MIN_PROPERTIES_FOR_AVERAGE} properties with enough monitored answers."}
        return {"value": round(sum(vals) / len(vals), 4), "properties": len(vals), "label": LABEL_MEASURED}

    prop_ids = [p.id for p in props]
    gap_counter: Counter = Counter()
    gap_props: dict[str, set] = {}
    if prop_ids:
        for g in db.query(AIContentGap).filter(AIContentGap.property_id.in_(prop_ids), AIContentGap.status == "open").all():
            key = g.topic_key or "general"
            gap_counter[key] += 1
            gap_props.setdefault(key, set()).add(g.property_id)
    shared_gaps = [
        {"topic_key": k, "properties": len(gap_props[k]), "gaps": n,
         "text": f"{len(gap_props[k])} properties are rarely mentioned in AI answers about {k.replace('_', ' ')}."}
        for k, n in gap_counter.most_common() if len(gap_props[k]) >= MIN_PROPERTIES_FOR_PATTERN
    ]

    domains: Counter = Counter()
    domain_props: dict[str, set] = {}
    if prop_ids:
        s_dt = datetime.combine(start, datetime.min.time())
        e_dt = datetime.combine(end + timedelta(days=1), datetime.min.time())
        pairs = (
            db.query(AIPropertyObservation.property_id, AICitation.domain)
            .join(AICitation, AICitation.response_id == AIPropertyObservation.response_id)
            .filter(AIPropertyObservation.property_id.in_(prop_ids), AIPropertyObservation.observed_at >= s_dt,
                    AIPropertyObservation.observed_at < e_dt)
            .all()
        )
        for pid, dom in pairs:
            domains[dom] += 1
            domain_props.setdefault(dom, set()).add(pid)
    top_sources = [{"domain": d, "citations": n, "properties": len(domain_props[d])} for d, n in domains.most_common(10)]

    return {
        "scope": {"company_id": company_id, "unassigned": unassigned, "properties": len(props)},
        "window": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "averages": {k: average(k) for k in ("ai_visibility", "citation_rate", "share_of_voice", "recommendation_rate")},
        "properties": rows,
        "shared_gaps": shared_gaps,
        "shared_gaps_label": LABEL_MODELED,
        "top_sources": top_sources,
        "note": "Averages include only properties with enough monitored answers. Patterns are counts, not causes.",
    }
