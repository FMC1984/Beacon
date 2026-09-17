"""Where the property stands: in its market, and against its own comp set.

Two different questions a regional manager asks. The comp set is the
competitors a person confirmed; the market is every community Beacon
monitors in the same city. Both ranks are MEASURED from monitored answers,
ties share a rank, and nothing is ranked below the sample minimum.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import AIDiscoveredEntity, AIPropertyObservation, Competitor, Mention, Property
from app.models.mention import ENTITY_COMPETITOR
from app.services.ai_visibility.reference import MIN_QUERIES_FOR_VISIBILITY
from app.services.observatory import LABEL_MEASURED, utc_today
from app.services.observatory.markets import market_members
from app.services.observatory.metrics import metrics_for_window
from app.services.observatory.tenancy import property_org_id
from app.services.observatory.topic_rankings import _rank, topic_rankings


def _comp_set(db: Session, prop: Property, days: int, today: date) -> dict:
    lo = datetime.combine(today - timedelta(days=days - 1), datetime.min.time())
    hi = datetime.combine(today + timedelta(days=1), datetime.min.time())
    competitors = db.query(Competitor).filter_by(property_id=prop.id).all()
    obs = (
        db.query(AIPropertyObservation.response_id, AIPropertyObservation.mentioned)
        .filter(AIPropertyObservation.property_id == prop.id, AIPropertyObservation.eligible.is_(True),
                AIPropertyObservation.observed_at >= lo, AIPropertyObservation.observed_at < hi)
        .all()
    )
    n = len(obs)
    if not competitors:
        return {"available": False, "reason": "No tracked competitors yet. Confirm the ones AI already names on the Competitors tab.",
                "answers": n}
    if n < MIN_QUERIES_FOR_VISIBILITY:
        return {"available": False, "reason": f"Needs at least {MIN_QUERIES_FOR_VISIBILITY} monitored answers ({n} so far).", "answers": n}
    counts: dict[int, set] = defaultdict(set)
    rids = [r for r, _ in obs]
    for rid, eid in db.query(Mention.response_id, Mention.entity_id).filter(
            Mention.response_id.in_(rids), Mention.entity_type == ENTITY_COMPETITOR,
            Mention.entity_id.in_([c.id for c in competitors])).all():
        counts[eid].add(rid)
    entities = [{"name": prop.name, "is_property": True, "mentions": sum(1 for _, m in obs if m)}]
    entities += [{"name": c.name, "is_property": False, "mentions": len(counts.get(c.id, ()))} for c in competitors]
    ranked = _rank(entities)
    mine = next((e for e in ranked if e["is_property"]), None)
    ahead = [e["name"] for e in ranked if not e["is_property"] and mine and e["rank"] < mine["rank"]]
    behind = [c.name for c in competitors if c.name not in ahead and not (mine and any(
        e["name"] == c.name and e["rank"] == mine["rank"] for e in ranked))]
    # Which questions the competitors ahead of us win.
    losing: dict[str, list[str]] = defaultdict(list)
    for t in topic_rankings(db, prop.id, days=days, today=today)["topics"]:
        if not t["sufficient"]:
            continue
        for e in t["ranked"]:
            if not e["is_property"] and (t["property_rank"] is None or e["rank"] < t["property_rank"]):
                losing[e["name"]].append((t["topic_key"] or "general").replace("_", " "))
    return {
        "available": True, "answers": n, "size": len(entities),
        "rank": mine["rank"] if mine else None,
        "tied": bool(mine and sum(1 for e in ranked if e["rank"] == mine["rank"]) > 1),
        "ranked": [{k: e[k] for k in ("name", "is_property", "mentions", "rank")} for e in ranked],
        "unranked": [e["name"] for e in entities if e["mentions"] == 0],
        "beating": len([c for c in competitors if c.name in behind]),
        "competitors": len(competitors),
        "ahead_of_you": [{"name": name, "winning_on": sorted(set(losing.get(name, [])))[:4]} for name in ahead],
    }


def _market(db: Session, prop: Property, days: int, today: date) -> dict:
    if prop.market_id is None:
        return {"available": False, "reason": "Add a city and state so Beacon can place this property in a market."}
    start, end = today - timedelta(days=days - 1), today
    members = market_members(db, prop.market_id, property_org_id(db, prop.id))
    rows = []
    for p in members:
        v = metrics_for_window(db, p.id, start, end)["ai_visibility"]["value"]
        if v is not None:
            rows.append({"name": p.name, "is_property": p.id == prop.id, "mentions": v})
    also_named = db.query(AIDiscoveredEntity).filter(AIDiscoveredEntity.market_id == prop.market_id).count()
    ranked = _rank(rows)
    mine = next((e for e in ranked if e["is_property"]), None)
    if mine is None:
        return {"available": False, "monitored": len(members), "also_named": also_named,
                "reason": "Not enough monitored answers for this property in the window."}
    return {
        "available": True, "rank": mine["rank"], "size": len(ranked), "monitored": len(members),
        "tied": sum(1 for e in ranked if e["rank"] == mine["rank"]) > 1,
        "ai_visibility": mine["mentions"], "also_named": also_named,
        "only_one": len(ranked) == 1,
    }


def property_standing(db: Session, property_id: int, days: int = 30, today: date | None = None) -> dict:
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    today = today or utc_today()
    return {
        "property_id": property_id, "data_label": LABEL_MEASURED,
        "window": {"start": (today - timedelta(days=days - 1)).isoformat(), "end": today.isoformat(), "days": days},
        "market": _market(db, prop, days, today),
        "comp_set": _comp_set(db, prop, days, today),
        "note": ("Market rank compares AI Visibility across the communities Beacon monitors in this city. Comp set rank "
                 "counts monitored answers naming you and each competitor you confirmed. Ties share a rank."),
    }
