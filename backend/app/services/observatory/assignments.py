"""Prompt assignments (Phase 19, slice 2): which clusters a property is
monitored for. Market and feature clusters are shared; a property
subscribes to the market clusters plus the feature clusters whose topic it
has a signal for (attributes, content, Search Console) or that are core.
Brand clusters are the property's own."""

from sqlalchemy.orm import Session

from app.models import AIPromptAssignment, AIPromptCluster, Property
from app.models.ai_prompt_library import (
    PROMPT_SCOPE_BRAND,
    PROMPT_SCOPE_FEATURE,
    PROMPT_SCOPE_MARKET,
)
from app.services.observatory.prompt_library import property_signal_topics
from app.services.observatory.tenancy import property_org_id


def assignment_key(*, cluster_id=None, prompt_id=None, property_id=None, market_id=None) -> str:
    return f"c{cluster_id or ''}|p{prompt_id or ''}|prop{property_id or ''}|mkt{market_id or ''}"


def assign(
    db: Session, *, cluster_id=None, prompt_id=None, property_id=None, market_id=None,
    organization_id=None, tier="standard_property", source="auto",
) -> tuple[AIPromptAssignment, bool]:
    key = assignment_key(cluster_id=cluster_id, prompt_id=prompt_id, property_id=property_id, market_id=market_id)
    row = db.query(AIPromptAssignment).filter_by(assignment_key=key).one_or_none()
    if row is not None:
        if not row.active:
            row.active = True
        return row, False
    row = AIPromptAssignment(
        organization_id=organization_id, cluster_id=cluster_id, prompt_id=prompt_id,
        property_id=property_id, market_id=market_id, assignment_key=key, tier=tier,
        active=True, source=source,
    )
    db.add(row)
    db.flush()
    return row, True


def subscribe_property(db: Session, property_id: int, tier: str = "standard_property") -> dict:
    """Assign the property to its market's market clusters, the feature
    clusters its signals justify, and its own brand clusters. Feature
    clusters without a signal are left unassigned (deactivated if they were
    auto-assigned before) so a property never pays for prompts about
    features it has no evidence for."""
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    org_id = property_org_id(db, property_id)
    signals = property_signal_topics(db, prop)
    created = 0
    assigned_cluster_ids: set[int] = set()

    if prop.market_id is not None:
        market_clusters = (
            db.query(AIPromptCluster)
            .filter(AIPromptCluster.market_id == prop.market_id, AIPromptCluster.property_id.is_(None))
            .all()
        )
        for cluster in market_clusters:
            wanted = cluster.scope == PROMPT_SCOPE_MARKET or (
                cluster.scope == PROMPT_SCOPE_FEATURE and cluster.topic_key in signals
            )
            if not wanted:
                continue
            _, was_created = assign(
                db, cluster_id=cluster.id, property_id=prop.id, market_id=prop.market_id,
                organization_id=org_id, tier=tier,
            )
            created += int(was_created)
            assigned_cluster_ids.add(cluster.id)

    for cluster in db.query(AIPromptCluster).filter_by(property_id=prop.id, scope=PROMPT_SCOPE_BRAND).all():
        _, was_created = assign(db, cluster_id=cluster.id, property_id=prop.id, organization_id=org_id, tier=tier)
        created += int(was_created)
        assigned_cluster_ids.add(cluster.id)

    deactivated = 0
    for row in db.query(AIPromptAssignment).filter_by(property_id=prop.id, source="auto", active=True).all():
        if row.cluster_id is not None and row.cluster_id not in assigned_cluster_ids:
            row.active = False
            deactivated += 1
    db.commit()
    return {
        "property_id": prop.id, "market_id": prop.market_id, "assignments_created": created,
        "assignments_active": len(assigned_cluster_ids), "assignments_deactivated": deactivated,
        "signal_topics": signals,
    }


def assignments_for_property(db: Session, property_id: int, active_only: bool = True) -> list[AIPromptAssignment]:
    q = db.query(AIPromptAssignment).filter_by(property_id=property_id)
    if active_only:
        q = q.filter(AIPromptAssignment.active.is_(True))
    return q.order_by(AIPromptAssignment.id).all()


def properties_for_cluster(db: Session, cluster_id: int) -> list[int]:
    return [
        pid for (pid,) in db.query(AIPromptAssignment.property_id)
        .filter(AIPromptAssignment.cluster_id == cluster_id, AIPromptAssignment.active.is_(True),
                AIPromptAssignment.property_id.isnot(None))
        .all()
    ]
