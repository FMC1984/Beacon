"""Hybrid retriever (Phase 15b): query -> candidate pool -> deterministic
rerank -> chunks joined to SQLite provenance.

Vector search PROPOSES candidates (a pool larger than top_k, optionally
pre-filtered by property/source/topic metadata); transparent weighted
components from rag_retrieval.json SELECT and ORDER them: semantic similarity,
keyword overlap, phrase match, topic overlap (from the Phase 15a enrichment),
entity overlap, and recency. No LLM influences ranking, ties break on
chroma_id, and every result carries its component scores (match_explanation)
so retrieval is debuggable.

The citation attached to each retrieved chunk is assembled here, in code, from
the rag_chunks registry (hard rule 6). Nora consumes these results unchanged;
no generation happens in this module.
"""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.models import Property, RAGChunk
from app.services.rag.embedder import Embedder
from app.services.rag.store import get_collection
from app.services.semantic import enrich_text
from app.services.semantic.text import find_phrase, load_reference, tokens


@dataclass(frozen=True)
class Citation:
    property_id: int | None
    property_name: str | None
    date_range: str
    source_table: str
    source_ref: str


@dataclass(frozen=True)
class RetrievedChunk:
    chroma_id: str
    text: str
    distance: float
    citation: Citation
    score: float = 0.0
    match_explanation: dict = field(default_factory=dict)


def _cfg() -> dict:
    return load_reference("rag_retrieval.json")


def _content_tokens(text: str) -> list[str]:
    stop = set(_cfg()["stopwords"])
    return [t for t in tokens(text) if t not in stop]


def _keyword_overlap(query_tokens: list[str], chunk_tokens: set[str]) -> tuple[float, list[str]]:
    if not query_tokens:
        return 0.0, []
    hits = sorted({t for t in query_tokens if t in chunk_tokens})
    return len(hits) / len(set(query_tokens)), hits


def _phrase_match(query_tokens: list[str], chunk_content_tokens: list[str]) -> tuple[float, list[str]]:
    """Fraction of query bigrams that appear in the chunk. Both sides are
    stopword-filtered, so 'washer dryer' matches 'washer and dryer'."""
    bigrams = [query_tokens[i : i + 2] for i in range(len(query_tokens) - 1)]
    if not bigrams:
        return 0.0, []
    hits = [" ".join(b) for b in bigrams if find_phrase(chunk_content_tokens, b)]
    return len(hits) / len(bigrams), sorted(set(hits))


def _overlap(query_items: set[str], chunk_items: set[str]) -> tuple[float, list[str]]:
    if not query_items:
        return 0.0, []
    hits = sorted(query_items & chunk_items)
    return len(hits) / len(query_items), hits


def _recency(period_end: date | None, anchor: date | None) -> float:
    """Newer chunks score higher, anchored to the newest candidate (data-
    relative, so no wall-clock nondeterminism). Undated chunks are neutral."""
    if period_end is None or anchor is None:
        return 0.5
    age_days = (anchor - period_end).days
    return max(0.0, min(1.0, 1.0 - age_days / 365))


def _where(property_id: int | None, source: str | None, topics: list[str] | None):
    clauses = []
    if property_id is not None:
        clauses.append({"property_id": property_id})
    if source:
        clauses.append({"source": source})
    if topics:
        topic_clauses = [{f"topic_{t}": True} for t in topics]
        clauses.append(topic_clauses[0] if len(topic_clauses) == 1 else {"$or": topic_clauses})
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def retrieve(
    db: Session,
    embedder: Embedder,
    query: str,
    property_id: int | None = None,
    top_k: int = 6,
    chroma_dir: str | None = None,
    source: str | None = None,
    topics: list[str] | None = None,
) -> list[RetrievedChunk]:
    collection = get_collection(chroma_dir, embedder.key)
    if collection.count() == 0:
        return []

    cfg = _cfg()
    pool = max(top_k * cfg["candidate_pool_multiplier"], cfg["min_candidate_pool"])
    query_vector = embedder.embed([query])[0]
    result = collection.query(
        query_embeddings=[query_vector],
        n_results=min(pool, collection.count()),
        where=_where(property_id, source, topics),
    )

    ids = result["ids"][0]
    documents = {i: d for i, d in zip(ids, result["documents"][0])}
    distances = {i: d for i, d in zip(ids, result["distances"][0])}

    rows = {
        r.chroma_id: r
        for r in db.query(RAGChunk).filter(RAGChunk.chroma_id.in_(ids)).all()
    }
    # Registry and collection out of sync; skip rather than cite nothing.
    ids = [i for i in ids if i in rows]
    if not ids:
        return []

    q_enrich = enrich_text(query)
    q_tokens = _content_tokens(query)
    q_concepts = set(q_enrich["topics"]) | set(q_enrich["normalized_terms"])
    q_entities = {e["value"].lower() for e in q_enrich["entities"]}
    anchor = max((rows[i].period_end for i in ids if rows[i].period_end), default=None)
    weights = cfg["weights"]

    scored = []
    for cid in ids:
        row = rows[cid]
        chunk_token_list = _content_tokens(documents[cid])
        chunk_tokens = set(chunk_token_list)
        enrichment = row.enrichment or {}
        c_concepts = set(enrichment.get("topics", [])) | set(
            enrichment.get("normalized_terms", [])
        )
        c_entities = {e["value"].lower() for e in enrichment.get("entities", [])}

        kw, kw_hits = _keyword_overlap(q_tokens, chunk_tokens)
        ph, ph_hits = _phrase_match(q_tokens, chunk_token_list)
        tp, tp_hits = _overlap(q_concepts, c_concepts)
        en, en_hits = _overlap(q_entities, c_entities)
        components = {
            # 1/(1+d) is monotonic in the raw distance and bounded (0, 1], so
            # it works for both L2 (Chroma default) and cosine spaces without
            # collapsing to 0 when distance exceeds 1.
            "semantic_similarity": round(1.0 / (1.0 + max(0.0, distances[cid])), 4),
            "keyword_overlap": round(kw, 4),
            "phrase_match": round(ph, 4),
            "topic_overlap": round(tp, 4),
            "entity_overlap": round(en, 4),
            "recency": round(_recency(row.period_end, anchor), 4),
        }
        score = round(
            sum(weights[k] * v for k, v in components.items()) / sum(weights.values()),
            4,
        )
        scored.append(
            (
                cid,
                score,
                {
                    "final_score": score,
                    "components": components,
                    "weights": weights,
                    "matched_keywords": kw_hits,
                    "matched_phrases": ph_hits,
                    "matched_topics": tp_hits,
                    "matched_entities": en_hits,
                },
            )
        )

    scored.sort(key=lambda x: (-x[1], x[0]))
    properties = {p.id: p.name for p in db.query(Property).all()}

    retrieved = []
    for cid, score, explanation in scored[:top_k]:
        row = rows[cid]
        retrieved.append(
            RetrievedChunk(
                chroma_id=cid,
                text=documents[cid],
                distance=distances[cid],
                score=score,
                match_explanation=explanation,
                citation=Citation(
                    property_id=row.property_id,
                    property_name=properties.get(row.property_id),
                    date_range=(
                        f"{row.period_start.isoformat()} to {row.period_end.isoformat()}"
                        if row.period_start and row.period_end
                        else "unknown"
                    ),
                    source_table=row.source_table,
                    source_ref=row.source_ref,
                ),
            )
        )
    return retrieved
