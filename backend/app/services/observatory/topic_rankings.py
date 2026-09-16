"""Visibility rankings by topic (Phase 19).

For each prompt cluster a property is scored on, rank every brand the
answers named (the property and its tracked competitors) by how many of
that cluster's answers named it. The grid this feeds shows, per question,
who AI reaches for first and where the property stands.

Counting only tracked competitors is deliberate: an untracked name can
appear as a discovery candidate on the Competitors tab, but it does not
enter a ranking until someone confirms it, so the grid never ranks the
property against a brand nobody has vetted.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import AIPromptCluster, AIPropertyObservation, AIVisibilityPrompt, Competitor, Mention, Property
from app.models.mention import ENTITY_COMPETITOR, ENTITY_PROPERTY
from app.services.ai_visibility.reference import MIN_QUERIES_FOR_VISIBILITY
from app.services.observatory import LABEL_MEASURED, utc_today
from app.services.reporting import DataState

GRID_COLUMNS = 10
NEEDS_WORK_RANK = 4  # property ranked 4th or worse, or unranked, with a sufficient sample


def _rank(entities: list[dict]) -> list[dict]:
    """Ties share a rank (1, 1, 3), matching competitive_ranking."""
    ranked = sorted((e for e in entities if e["mentions"] > 0), key=lambda e: (-e["mentions"], e["name"]))
    seen, rank, prev = 0, 0, None
    for e in ranked:
        seen += 1
        if e["mentions"] != prev:
            rank, prev = seen, e["mentions"]
        e["rank"] = rank
    return ranked


def topic_rankings(db: Session, property_id: int, days: int = 30, today: date | None = None) -> dict:
    today = today or utc_today()
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    start = datetime.combine(today - timedelta(days=days - 1), datetime.min.time())
    end = datetime.combine(today + timedelta(days=1), datetime.min.time())
    competitors = db.query(Competitor).filter_by(property_id=property_id).all()
    comp_names = {c.id: c.name for c in competitors}

    obs = (
        db.query(AIPropertyObservation)
        .filter(AIPropertyObservation.property_id == property_id, AIPropertyObservation.eligible.is_(True),
                AIPropertyObservation.cluster_id.isnot(None),
                AIPropertyObservation.observed_at >= start, AIPropertyObservation.observed_at < end)
        .all()
    )
    by_cluster: dict[int, list[AIPropertyObservation]] = defaultdict(list)
    for o in obs:
        by_cluster[o.cluster_id].append(o)
    response_ids = [o.response_id for o in obs]
    mentions_by_response: dict[int, set[tuple[str, int]]] = defaultdict(set)
    if response_ids and competitors:
        rows = db.query(Mention.response_id, Mention.entity_type, Mention.entity_id).filter(
            Mention.response_id.in_(response_ids), Mention.entity_type == ENTITY_COMPETITOR,
            Mention.entity_id.in_(list(comp_names))).all()
        for rid, etype, eid in rows:
            mentions_by_response[rid].add((etype, eid))

    labels: dict[int, tuple[str, str | None, int]] = {}
    if by_cluster:
        for c in db.query(AIPromptCluster).filter(AIPromptCluster.id.in_(list(by_cluster))).all():
            p = db.get(AIVisibilityPrompt, c.representative_prompt_id) if c.representative_prompt_id else None
            labels[c.id] = (p.prompt_text if p else c.label, c.topic_key, c.importance or 3)

    topics = []
    for cluster_id, rows in by_cluster.items():
        n = len(rows)
        counts: dict[tuple[str, int], int] = defaultdict(int)
        for o in rows:
            if o.mentioned:
                counts[(ENTITY_PROPERTY, property_id)] += 1
            for key in mentions_by_response.get(o.response_id, ()):
                counts[key] += 1
        entities = [{"entity_type": ENTITY_PROPERTY, "entity_id": property_id, "name": prop.name,
                     "is_property": True, "mentions": counts.get((ENTITY_PROPERTY, property_id), 0)}]
        for cid, name in comp_names.items():
            entities.append({"entity_type": ENTITY_COMPETITOR, "entity_id": cid, "name": name,
                             "is_property": False, "mentions": counts.get((ENTITY_COMPETITOR, cid), 0)})
        for e in entities:
            e["share"] = round(e["mentions"] / n, 4) if n else None
        ranked = _rank(entities)
        sufficient = n >= MIN_QUERIES_FOR_VISIBILITY
        prop_rank = next((e["rank"] for e in ranked if e["is_property"]), None)
        label, topic_key, importance = labels.get(cluster_id, ("Prompt", None, 3))
        topics.append({
            "cluster_id": cluster_id, "prompt": label, "topic_key": topic_key, "importance": importance,
            "answers": n, "sufficient": sufficient,
            "state": (DataState.COMPLETE if sufficient else DataState.INSUFFICIENT_SAMPLE).value,
            "property_rank": prop_rank if sufficient else None,
            "property_mentions": counts.get((ENTITY_PROPERTY, property_id), 0),
            "needs_work": bool(sufficient and (prop_rank is None or prop_rank >= NEEDS_WORK_RANK)),
            "leader": ranked[0]["name"] if ranked else None,
            "ranked": [{k: v for k, v in e.items() if k != "entity_type"} for e in ranked[:GRID_COLUMNS]],
        })
    topics.sort(key=lambda t: (not t["sufficient"], t["property_rank"] is None, t["property_rank"] or 99, -t["importance"]))
    return {
        "property_id": property_id,
        "data_label": LABEL_MEASURED,
        "window": {"start": (today - timedelta(days=days - 1)).isoformat(), "end": today.isoformat(), "days": days},
        "minimum_sample": MIN_QUERIES_FOR_VISIBILITY,
        "tracked_competitors": len(competitors),
        "topics": topics,
        "summary": {
            "topics": len(topics),
            "leading": sum(1 for t in topics if t["property_rank"] == 1),
            "needs_work": sum(1 for t in topics if t["needs_work"]),
        },
        "note": ("Ranks count only the property and the competitors you track, by how many of a question's "
                 "monitored answers named each. Ties share a rank. Below the minimum sample no rank is claimed."),
    }
