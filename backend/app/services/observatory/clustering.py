"""Prompt clustering (Phase 19, slice 2).

Wording variants of the same question are grouped so routine monitoring
runs one representative per cluster and rotates the rest. Deterministic:
prompts are bucketed by (market or property, scope, topic_key, intent),
embedded through Beacon's embedding provider (deterministic in demo/tests),
and greedily agglomerated in id order against a cosine threshold. Same
inputs, same clusters. Embeddings are cached by prompt text hash.
"""

import math
from array import array
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Submarket, AIPromptCluster, AIPromptEmbedding, AIVisibilityPrompt
from app.providers.registry import get_embedding_provider
from app.services.observatory.prompt_library import prompt_hash

CLUSTERING_VERSION = 1


def pack(vec: list[float]) -> bytes:
    return array("f", vec).tobytes()


def unpack(blob: bytes) -> list[float]:
    a = array("f")
    a.frombytes(blob)
    return list(a)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


def _mean(vectors: list[list[float]]) -> list[float]:
    n = len(vectors)
    return [sum(v[i] for v in vectors) / n for i in range(len(vectors[0]))]


def embed_prompts(db: Session, prompts: list[AIVisibilityPrompt], provider=None) -> dict[int, list[float]]:
    """Return {prompt_id: vector}, embedding only prompts whose text hash or
    model changed since the last time."""
    provider = provider or get_embedding_provider()
    model = provider.key
    vectors: dict[int, list[float]] = {}
    todo: list[AIVisibilityPrompt] = []
    for p in prompts:
        h = p.prompt_hash or prompt_hash(p.prompt_text)
        cached = db.get(AIPromptEmbedding, p.id)
        if cached is not None and cached.prompt_hash == h and cached.model == model:
            vectors[p.id] = unpack(cached.vector)
        else:
            todo.append(p)
    if todo:
        embedded = provider.embed([p.prompt_text for p in todo])
        for p, vec in zip(todo, embedded):
            h = p.prompt_hash or prompt_hash(p.prompt_text)
            row = db.get(AIPromptEmbedding, p.id)
            if row is None:
                row = AIPromptEmbedding(prompt_id=p.id, model=model, dim=len(vec), vector=pack(vec), prompt_hash=h)
                db.add(row)
            else:
                row.model, row.dim, row.vector, row.prompt_hash = model, len(vec), pack(vec), h
            vectors[p.id] = list(vec)
        db.flush()
    return vectors


@dataclass
class ClusterReport:
    clusters_total: int = 0
    clusters_created: int = 0
    prompts_clustered: int = 0
    embedded_model: str | None = None
    buckets: list[dict] = field(default_factory=list)


def _bucket_key(p: AIVisibilityPrompt) -> tuple:
    return (p.market_id if p.property_id is None else None, p.property_id, p.scope, p.topic_key, p.intent,
            p.persona, p.submarket_id)


def _geography(db: Session, submarket_id: int | None) -> str | None:
    if submarket_id is None:
        return None
    sm = db.get(Submarket, submarket_id)
    return sm.slug if sm else None


def cluster_prompts(
    db: Session,
    *,
    market_id: int | None = None,
    property_id: int | None = None,
    scope: str | None = None,
    threshold: float | None = None,
    provider=None,
) -> ClusterReport:
    """(Re)cluster the active prompts in scope. Existing cluster rows are
    reused when the representative prompt still lands in them; otherwise
    new clusters are created and stale empty ones removed."""
    threshold = threshold if threshold is not None else settings.ai_cluster_threshold
    provider = provider or get_embedding_provider()
    q = db.query(AIVisibilityPrompt).filter(AIVisibilityPrompt.active.is_(True))
    if market_id is not None:
        q = q.filter(AIVisibilityPrompt.market_id == market_id, AIVisibilityPrompt.property_id.is_(None))
    if property_id is not None:
        q = q.filter(AIVisibilityPrompt.property_id == property_id)
    if scope:
        q = q.filter(AIVisibilityPrompt.scope == scope)
    prompts = q.order_by(AIVisibilityPrompt.id).all()
    report = ClusterReport(embedded_model=provider.key)
    if not prompts:
        return report

    vectors = embed_prompts(db, prompts, provider=provider)
    buckets: dict[tuple, list[AIVisibilityPrompt]] = {}
    for p in prompts:
        buckets.setdefault(_bucket_key(p), []).append(p)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    touched_cluster_ids: set[int] = set()
    for key, members in buckets.items():
        groups: list[dict] = []  # {"members": [...], "centroid": [...]}
        for p in members:  # id order -> deterministic
            vec = vectors[p.id]
            best, best_sim = None, -1.0
            for g in groups:
                sim = cosine(vec, g["centroid"])
                if sim > best_sim:
                    best, best_sim = g, sim
            if best is not None and best_sim >= threshold:
                best["members"].append(p)
                best["centroid"] = _mean([vectors[m.id] for m in best["members"]])
            else:
                groups.append({"members": [p], "centroid": list(vec)})

        for g in groups:
            members_sorted = sorted(g["members"], key=lambda m: (-(m.importance or 0), m.id))
            rep = members_sorted[0]
            cluster = None
            existing_ids = {m.cluster_id for m in g["members"] if m.cluster_id}
            if existing_ids:
                cluster = db.get(AIPromptCluster, sorted(existing_ids)[0])
            if cluster is None:
                cluster = AIPromptCluster(
                    organization_id=rep.organization_id, market_id=rep.market_id if rep.property_id is None else None,
                    property_id=rep.property_id, scope=rep.scope, label=rep.prompt_text[:300],
                    topic_key=rep.topic_key, intent=rep.intent, funnel_stage=rep.funnel_stage,
                    importance=rep.importance or 3, clustering_version=CLUSTERING_VERSION,
                )
                db.add(cluster)
                db.flush()
                report.clusters_created += 1
            cluster.label = rep.prompt_text[:300]
            cluster.persona = rep.persona
            cluster.geography = _geography(db, rep.submarket_id)
            cluster.representative_prompt_id = rep.id
            cluster.variant_count = len(g["members"])
            cluster.centroid = pack(g["centroid"])
            cluster.embedding_model = provider.key
            cluster.importance = max((m.importance or 0) for m in g["members"]) or 3
            cluster.updated_at = now
            touched_cluster_ids.add(cluster.id)
            for m in g["members"]:
                m.cluster_id = cluster.id
                m.is_representative = m.id == rep.id
            report.prompts_clustered += len(g["members"])
        report.buckets.append({"key": [k for k in key], "clusters": len(groups), "prompts": len(members)})

    # Drop clusters in scope that no prompt references any more.
    stale_q = db.query(AIPromptCluster).filter(AIPromptCluster.id.notin_(touched_cluster_ids or [0]))
    if market_id is not None:
        stale_q = stale_q.filter(AIPromptCluster.market_id == market_id, AIPromptCluster.property_id.is_(None))
    if property_id is not None:
        stale_q = stale_q.filter(AIPromptCluster.property_id == property_id)
    if scope:
        stale_q = stale_q.filter(AIPromptCluster.scope == scope)
    for stale in stale_q.all():
        if not db.query(AIVisibilityPrompt.id).filter_by(cluster_id=stale.id).first():
            db.delete(stale)
    db.commit()
    report.clusters_total = len(touched_cluster_ids)
    return report


def rotate_variant(db: Session, cluster_id: int, period_index: int) -> AIVisibilityPrompt | None:
    """The prompt to run for this cluster in a given period: the
    representative in period 0, then variants round-robin, so wording
    rotates without every variant running every time."""
    members = (
        db.query(AIVisibilityPrompt)
        .filter_by(cluster_id=cluster_id, active=True, approved=True)
        .order_by(AIVisibilityPrompt.is_representative.desc(), AIVisibilityPrompt.id)
        .all()
    )
    if not members:
        return None
    return members[period_index % len(members)]
