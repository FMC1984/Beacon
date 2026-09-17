"""AI Visibility by area and by audience (flow P3).

Groups the property's per-cluster daily rollups by the cluster's geography
(a submarket slug from an operator-asserted neighborhood) and persona (an
audience the Property Context type implies or the operator listed). The
figure per group is AI Visibility with the usual sample gate; a group with
too few answers shows no rate. Nothing is inferred: a property without a
neighborhood has no area rows, and the panel says why.
"""

from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AIClusterVisibilityDaily, AIPromptCluster, Property, Submarket
from app.services.observatory import LABEL_MEASURED, utc_today
from app.services.observatory.metrics import _window, metric_from_counts
from app.services.observatory.prompt_library import property_personas, templates


def _rows(db: Session, property_id: int, start: date, end: date, column) -> list[tuple[str, int, int, int]]:
    """(dimension value, clusters, mentioned, eligible) for clusters that
    carry the dimension, over the window."""
    rows = (
        db.query(column, func.count(func.distinct(AIPromptCluster.id)),
                 func.sum(AIClusterVisibilityDaily.mentioned_count), func.sum(AIClusterVisibilityDaily.eligible_count))
        .join(AIPromptCluster, AIPromptCluster.id == AIClusterVisibilityDaily.cluster_id)
        .filter(AIClusterVisibilityDaily.property_id == property_id, column.isnot(None),
                AIClusterVisibilityDaily.day >= start, AIClusterVisibilityDaily.day <= end)
        .group_by(column)
        .all()
    )
    return [(str(k), int(c or 0), int(m or 0), int(e or 0)) for k, c, m, e in rows]


def visibility_dimensions(db: Session, property_id: int, days: int = 30, today: date | None = None) -> dict:
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    today = today or utc_today()
    start, end = _window(days, today)
    persona_labels = templates().get("personas", {})
    submarkets = {sm.slug: sm.name for sm in db.query(Submarket).filter_by(market_id=prop.market_id).all()} if prop.market_id else {}
    own_geo = db.get(Submarket, prop.submarket_id).slug if prop.submarket_id else None

    def pack(rows, labels):
        out = []
        for key, clusters, mentioned, eligible in rows:
            out.append({
                "key": key, "label": labels.get(key, key.replace("_", " ")), "clusters": clusters, "answers": eligible,
                "ai_visibility": metric_from_counts("ai_visibility", mentioned, eligible),
            })
        out.sort(key=lambda r: (-(r["ai_visibility"]["value"] or 0), r["label"]))
        return out

    return {
        "property_id": property_id,
        "data_label": LABEL_MEASURED,
        "window": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "property_geography": own_geo,
        "property_personas": property_personas(db, prop),
        "regions": pack(_rows(db, property_id, start, end, AIPromptCluster.geography), submarkets),
        "personas": pack(_rows(db, property_id, start, end, AIPromptCluster.persona), persona_labels),
        "note": ("Area rows come from neighborhood questions (set on the property); audience rows from persona "
                 "questions (from the Property Context type). Below the minimum sample no rate is shown."),
    }
