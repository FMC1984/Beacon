"""Beacon Prompt Opportunity Score (Phase 19, slice 3). MODELED, 0-100,
configurable weights, every contributor listed with its value or marked
UNAVAILABLE. This is explicitly NOT prompt search volume."""

import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AIClusterVisibilityDaily, AIPromptCluster, GSCPerformanceDaily
from app.services.observatory import LABEL_MODELED, LABEL_UNAVAILABLE
from app.services.observatory.taxonomy import topic as taxonomy_topic
from app.services.reporting import previous_window

_REFERENCE = Path(__file__).resolve().parent.parent.parent / "reference_data" / "ai_opportunity_weights.json"


@lru_cache(maxsize=1)
def _config() -> dict:
    return json.loads(_REFERENCE.read_text())


def weights(overrides: dict | None = None) -> dict:
    w = dict(_config()["weights"])
    for k, v in (overrides or {}).items():
        if k in w:
            w[k] = float(v)
    return w


def _cluster_counts(db: Session, property_id: int, cluster_id: int, start: date, end: date) -> tuple[int, int, int]:
    row = (
        db.query(
            func.coalesce(func.sum(AIClusterVisibilityDaily.eligible_count), 0),
            func.coalesce(func.sum(AIClusterVisibilityDaily.mentioned_count), 0),
            func.coalesce(func.sum(AIClusterVisibilityDaily.competitor_win_count), 0),
        )
        .filter(
            AIClusterVisibilityDaily.property_id == property_id,
            AIClusterVisibilityDaily.cluster_id == cluster_id,
            AIClusterVisibilityDaily.day >= start,
            AIClusterVisibilityDaily.day <= end,
        )
        .one()
    )
    return int(row[0]), int(row[1]), int(row[2])


def _search_demand(db: Session, property_id: int, topic_key: str | None) -> float | None:
    """0-1 share of the property's Search Console impressions whose queries
    mention the topic's terms, scaled to the largest topic. None when the
    property has no Search Console data (UNAVAILABLE)."""
    total = db.query(func.coalesce(func.sum(GSCPerformanceDaily.impressions), 0)).filter(
        GSCPerformanceDaily.property_id == property_id).scalar()
    if not total:
        return None
    t = taxonomy_topic(topic_key or "")
    if not t:
        return 0.0
    rows = db.query(GSCPerformanceDaily.query, func.sum(GSCPerformanceDaily.impressions)).filter(
        GSCPerformanceDaily.property_id == property_id, GSCPerformanceDaily.query.isnot(None)
    ).group_by(GSCPerformanceDaily.query).all()
    terms = [term.lower() for term in t["terms"]]
    matched = sum(imp for q, imp in rows if any(term in (q or "").lower() for term in terms))
    return min(1.0, matched / total) if total else 0.0


def prompt_opportunity_score(
    db: Session, property_id: int, cluster_id: int, days: int = 30, today: date | None = None,
    weight_overrides: dict | None = None,
) -> dict:
    today = today or date.today()
    start, end = today - timedelta(days=max(days, 1) - 1), today
    prev_start, prev_end = previous_window(start, end)
    cluster = db.get(AIPromptCluster, cluster_id)
    if cluster is None:
        raise ValueError("Cluster not found.")

    eligible, mentioned, comp_wins = _cluster_counts(db, property_id, cluster_id, start, end)
    p_eligible, p_mentioned, _ = _cluster_counts(db, property_id, cluster_id, prev_start, prev_end)

    contributors: dict[str, dict] = {}
    if eligible:
        contributors["competitor_presence"] = {"value": round(comp_wins / eligible, 4), "available": True,
                                               "detail": f"{comp_wins} of {eligible} responses"}
        contributors["visibility_gap"] = {"value": round(1 - mentioned / eligible, 4), "available": True,
                                          "detail": f"mentioned in {mentioned} of {eligible}"}
    else:
        contributors["competitor_presence"] = {"value": None, "available": False, "detail": "no observations yet"}
        contributors["visibility_gap"] = {"value": None, "available": False, "detail": "no observations yet"}
    contributors["topic_importance"] = {"value": round((cluster.importance or 3) / 5, 4), "available": True,
                                        "detail": f"importance {cluster.importance}/5"}
    demand = _search_demand(db, property_id, cluster.topic_key)
    contributors["search_demand"] = (
        {"value": round(demand, 4), "available": True, "detail": "share of Search Console impressions on this topic"}
        if demand is not None else
        {"value": None, "available": False, "detail": "Search Console not connected"}
    )
    if eligible and p_eligible:
        cur_v, prev_v = mentioned / eligible, p_mentioned / p_eligible
        drop = max(0.0, min(1.0, (prev_v - cur_v + 1) / 2))  # 0.5 = flat, 1 = full decline
        contributors["momentum"] = {"value": round(drop, 4), "available": True,
                                    "detail": f"visibility {round(prev_v*100)}% -> {round(cur_v*100)}%"}
    else:
        contributors["momentum"] = {"value": None, "available": False, "detail": "needs two periods of observations"}

    w = weights(weight_overrides)
    available = {k: v for k, v in w.items() if contributors[k]["available"]}
    total_w = sum(available.values())
    score = None
    if total_w > 0:
        score = round(100 * sum(contributors[k]["value"] * (weight / total_w) for k, weight in available.items()))
    return {
        "cluster_id": cluster_id,
        "property_id": property_id,
        "score": score,
        "data_label": LABEL_MODELED if score is not None else LABEL_UNAVAILABLE,
        "window": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "weights": w,
        "effective_weights": {k: round(v / total_w, 4) for k, v in available.items()} if total_w else {},
        "contributors": contributors,
        "explanation": (
            "Weighted sum of the available contributors; weights of unavailable "
            "contributors are redistributed. This is not prompt search volume."
        ),
    }
