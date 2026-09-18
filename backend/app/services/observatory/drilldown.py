"""Drilldown: every Observatory number walks back to the rows that made it.

Three views that Profound-style tools sell as features and Beacon already
has the data for, plus the generic evidence list every metric card opens:

  fanouts        the retrieval queries the provider ran (OBSERVED), grouped
                 per prompt cluster: what the AI searched for, not what a
                 consumer typed. Coverage varies by provider and run, and
                 the report says so.
  position       where the property fell among the brands an answer named
                 (rank 1 = named first). MEASURED from mention_rank.
  sentiment      the topics attached to positive and negative mentions,
                 aggregated from the deterministic semantic layer, so
                 "positive because of amenities and location" is a count of
                 real answers rather than a summary a model wrote.
  evidence       the observations behind any metric, filterable to exactly
                 the rows that count toward its numerator or denominator,
                 so a KPI is never a number without a list behind it.
"""

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    AICitation,
    AIPromptCluster,
    AIPropertyObservation,
    AISearchQuery,
    AIVisibilityPrompt,
    AIVisibilityQuery,
    Property,
)
from app.services.ai_visibility.reference import MIN_QUERIES_FOR_VISIBILITY
from app.services.observatory import LABEL_MEASURED, LABEL_MODELED, LABEL_OBSERVED, utc_today
from app.services.reporting import DataState, compare_points, previous_window
from app.services.semantic import enrich_text
from app.services.semantic.text import load_reference

MAX_EVIDENCE_ROWS = 200

FANOUT_NOTE = (
    "These are the searches the AI provider reported running to build its answer, not searches "
    "people typed. Coverage is not guaranteed: some providers and some runs report none."
)
POSITION_NOTE = (
    "Rank 1 means the property was the first brand named in the answer, counting the property "
    "and its tracked competitors. Answers that did not name the property have no position."
)
SENTIMENT_NOTE = (
    "Topics are attached by the deterministic semantic layer to the sentence around each mention. "
    "A topic listed as a reason is a count of answers, not a summary written by a model."
)


def _bounds(days: int, today: date) -> tuple[datetime, datetime]:
    start = today - timedelta(days=days - 1)
    return datetime.combine(start, datetime.min.time()), datetime.combine(today + timedelta(days=1), datetime.min.time())


def _observations(db: Session, property_id: int, days: int, today: date) -> list[AIPropertyObservation]:
    lo, hi = _bounds(days, today)
    return (
        db.query(AIPropertyObservation)
        .filter(AIPropertyObservation.property_id == property_id,
                AIPropertyObservation.eligible.is_(True),
                AIPropertyObservation.observed_at >= lo,
                AIPropertyObservation.observed_at < hi)
        .order_by(AIPropertyObservation.observed_at.desc())
        .all()
    )


# --- query fanouts -----------------------------------------------------------


def query_fanouts(db: Session, property_id: int, days: int = 30, today: date | None = None) -> dict:
    today = today or utc_today()
    obs = _observations(db, property_id, days, today)
    response_ids = sorted({o.response_id for o in obs})
    cluster_of = {o.response_id: o.cluster_id for o in obs}
    if not response_ids:
        return {"property_id": property_id, "data_label": LABEL_OBSERVED, "note": FANOUT_NOTE,
                "window_days": days, "responses": 0, "responses_with_queries": 0,
                "coverage": None, "prompts": [], "state": DataState.EMPTY.value}

    rows = (
        db.query(AISearchQuery.response_id, AISearchQuery.query_text, AISearchQuery.provider)
        .filter(AISearchQuery.response_id.in_(response_ids))
        .all()
    )
    by_cluster: dict[int | None, Counter] = defaultdict(Counter)
    responses_with: dict[int | None, set] = defaultdict(set)
    for rid, text, _provider in rows:
        key = " ".join((text or "").lower().split())
        if not key:
            continue
        by_cluster[cluster_of.get(rid)][key] += 1
        responses_with[cluster_of.get(rid)].add(rid)

    cluster_ids = [c for c in by_cluster if c is not None]
    labels = {}
    if cluster_ids:
        for c in db.query(AIPromptCluster).filter(AIPromptCluster.id.in_(cluster_ids)).all():
            prompt = db.get(AIVisibilityPrompt, c.representative_prompt_id) if c.representative_prompt_id else None
            labels[c.id] = prompt.prompt_text if prompt else c.label
    responses_per_cluster = Counter(cluster_of[rid] for rid in response_ids)

    prompts = []
    for cluster_id, counter in by_cluster.items():
        total = sum(counter.values())
        executions = responses_per_cluster.get(cluster_id, 0)
        prompts.append({
            "cluster_id": cluster_id,
            "prompt": labels.get(cluster_id, "Property brand prompts" if cluster_id is None else "Prompt"),
            "executions": executions,
            "executions_with_queries": len(responses_with[cluster_id]),
            "query_count": total,
            "distinct_queries": len(counter),
            "avg_queries_per_execution": round(total / executions, 2) if executions else None,
            "variations": [
                {"query": q, "count": n, "share": round(n / total, 4) if total else None}
                for q, n in counter.most_common(25)
            ],
        })
    prompts.sort(key=lambda p: -p["query_count"])
    with_queries = len({rid for rid, _, _ in rows})
    return {
        "property_id": property_id,
        "data_label": LABEL_OBSERVED,
        "note": FANOUT_NOTE,
        "window_days": days,
        "responses": len(response_ids),
        "responses_with_queries": with_queries,
        "coverage": round(with_queries / len(response_ids), 4),
        "prompts": prompts,
        "state": DataState.COMPLETE.value,
    }


# --- average position --------------------------------------------------------


def _position_stats(obs: list[AIPropertyObservation]) -> dict:
    ranks = [o.mention_rank for o in obs if o.mentioned and o.mention_rank]
    mentioned = sum(1 for o in obs if o.mentioned)
    dist = Counter(min(r, 5) for r in ranks)
    return {
        "eligible": len(obs),
        "mentioned": mentioned,
        "ranked": len(ranks),
        "average_position": round(sum(ranks) / len(ranks), 2) if ranks else None,
        "first_named": sum(1 for r in ranks if r == 1),
        "first_named_rate": round(sum(1 for r in ranks if r == 1) / len(obs), 4) if obs else None,
        "distribution": {f"{k}{'+' if k == 5 else ''}": dist.get(k, 0) for k in range(1, 6)},
    }


def average_position(db: Session, property_id: int, days: int = 30, today: date | None = None) -> dict:
    today = today or utc_today()
    start, end = today - timedelta(days=days - 1), today
    p_start, p_end = previous_window(start, end)
    cur = _observations(db, property_id, days, today)
    prev = _observations(db, property_id, days, p_end)
    cur_s, prev_s = _position_stats(cur), _position_stats(prev)
    sufficient = cur_s["ranked"] >= MIN_QUERIES_FOR_VISIBILITY

    by_cluster: dict[int | None, list] = defaultdict(list)
    for o in cur:
        by_cluster[o.cluster_id].append(o)
    labels = {}
    ids = [c for c in by_cluster if c is not None]
    if ids:
        for c in db.query(AIPromptCluster).filter(AIPromptCluster.id.in_(ids)).all():
            labels[c.id] = c.label
    per_prompt = []
    for cluster_id, rows in by_cluster.items():
        s = _position_stats(rows)
        per_prompt.append({"cluster_id": cluster_id, "prompt": labels.get(cluster_id, "Brand prompts"), **s,
                           "state": (DataState.COMPLETE if s["ranked"] >= MIN_QUERIES_FOR_VISIBILITY
                                     else DataState.INSUFFICIENT_SAMPLE).value})
    per_prompt.sort(key=lambda r: (r["average_position"] is None, r["average_position"] or 0))

    # Lower is better, so compare_points direction is inverted by the caller.
    delta = (round(cur_s["average_position"] - prev_s["average_position"], 2)
             if cur_s["average_position"] is not None and prev_s["average_position"] is not None else None)
    return {
        "property_id": property_id,
        "data_label": LABEL_MEASURED,
        "note": POSITION_NOTE,
        "window": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "current": cur_s,
        "previous": prev_s,
        "change": delta,
        "lower_is_better": True,
        "state": (DataState.COMPLETE if sufficient else DataState.INSUFFICIENT_SAMPLE).value,
        "minimum_sample": MIN_QUERIES_FOR_VISIBILITY,
        "first_named_comparison": compare_points(cur_s["first_named_rate"], prev_s["first_named_rate"]),
        "by_prompt": per_prompt,
    }


# --- sentiment with reasons --------------------------------------------------


def sentiment_reasons(db: Session, property_id: int, days: int = 30, today: date | None = None) -> dict:
    today = today or utc_today()
    obs = [o for o in _observations(db, property_id, days, today) if o.mentioned]
    labels = {t["key"]: t["label"] for t in load_reference("semantic_topics.json")["topics"]}
    positive: Counter = Counter()
    negative: Counter = Counter()
    counts = Counter(o.sentiment or "neutral" for o in obs)
    quotes: dict[str, list[str]] = defaultdict(list)
    for o in obs:
        if not o.context_excerpt:
            continue
        for topic, label in enrich_text(o.context_excerpt)["sentiment_by_topic"].items():
            if label == "positive":
                positive[topic] += 1
            elif label == "negative":
                negative[topic] += 1
            else:
                continue
            if len(quotes[f"{label}:{topic}"]) < 2:
                quotes[f"{label}:{topic}"].append(" ".join(o.context_excerpt.split())[:200])

    scored = counts["positive"] + counts["negative"]
    sufficient = len(obs) >= MIN_QUERIES_FOR_VISIBILITY

    def reasons(counter: Counter, polarity: str) -> list[dict]:
        return [
            {"topic": t, "label": labels.get(t, t), "answers": n, "quotes": quotes[f"{polarity}:{t}"]}
            for t, n in counter.most_common(6)
        ]

    return {
        "property_id": property_id,
        "data_label": LABEL_MODELED,
        "note": SENTIMENT_NOTE,
        "window_days": days,
        "mentions": len(obs),
        "counts": {k: counts.get(k, 0) for k in ("positive", "neutral", "negative")},
        # Share of answers that carried any sentiment at all, and of those, positive.
        "positive_share": round(counts["positive"] / scored, 4) if scored and sufficient else None,
        "neutral_share": round(counts["neutral"] / len(obs), 4) if obs and sufficient else None,
        "positive_reasons": reasons(positive, "positive"),
        "negative_reasons": reasons(negative, "negative"),
        "state": (DataState.COMPLETE if sufficient else DataState.INSUFFICIENT_SAMPLE).value,
        "minimum_sample": MIN_QUERIES_FOR_VISIBILITY,
    }


# --- generic evidence --------------------------------------------------------

# Which rows count toward a metric's numerator. Denominator is every eligible
# observation unless stated. Keeping this in one table means the drilldown
# and the metric can never disagree about what "counts".
EVIDENCE_FILTERS = {
    "ai_visibility": ("mentioned", "Answers where the property was named"),
    "citation_rate": ("cited", "Answers that cited the property's own site"),
    "recommendation_rate": ("recommended", "Answers where the property was classified as recommended"),
    "competitor_win_rate": ("competitor_win", "Answers naming a tracked competitor but not the property"),
    "share_of_voice": ("mentioned", "Answers where the property was named"),
    "citation_share": ("cited", "Answers that cited the property's own site"),
    "average_position": ("ranked", "Answers where the property was named, with its position"),
    "sentiment_positive": ("positive", "Mentions the semantic layer read as positive"),
    "sentiment_negative": ("negative", "Mentions the semantic layer read as negative"),
    # Alias for the Overview's AI Sentiment card: same filter as sentiment_positive
    # (its numerator), so clicking the headline number opens the rows behind it.
    "ai_sentiment": ("positive", "Mentions the semantic layer read as positive"),
    "all": ("all", "Every eligible monitored answer"),
}


def _passes(o: AIPropertyObservation, key: str) -> bool:
    return {
        "mentioned": bool(o.mentioned),
        "cited": bool(o.cited),
        "recommended": o.recommended is True,
        "competitor_win": bool(o.competitor_mentioned_count) and not o.mentioned,
        "ranked": bool(o.mentioned and o.mention_rank),
        "positive": o.sentiment == "positive",
        "negative": o.sentiment == "negative",
        "all": True,
    }[key]


def evidence(
    db: Session, property_id: int, metric: str, days: int = 30, today: date | None = None,
    cluster_id: int | None = None, only_counting: bool = True, limit: int = 50, offset: int = 0,
) -> dict:
    """The observations behind a metric. `only_counting` restricts to the rows
    in the numerator; False returns the whole denominator with a flag."""
    if metric not in EVIDENCE_FILTERS:
        raise ValueError(f"Unknown metric '{metric}'.")
    key, description = EVIDENCE_FILTERS[metric]
    today = today or utc_today()
    obs = _observations(db, property_id, days, today)
    if cluster_id is not None:
        obs = [o for o in obs if o.cluster_id == cluster_id]
    counting = [o for o in obs if _passes(o, key)]
    rows = counting if only_counting else obs
    page = rows[offset: offset + min(limit, MAX_EVIDENCE_ROWS)]

    response_ids = [o.response_id for o in page]
    prompts = {}
    cites: dict[int, list] = defaultdict(list)
    if response_ids:
        for q in db.query(AIVisibilityQuery).filter(AIVisibilityQuery.id.in_(response_ids)).all():
            prompts[q.id] = (q.prompt_text, q.raw_response_text)
        for c in (db.query(AICitation).filter(AICitation.response_id.in_(response_ids))
                  .order_by(AICitation.citation_order).all()):
            cites[c.response_id].append({"url": c.url, "domain": c.domain, "source_type": c.source_type})
    cluster_labels = {}
    cids = {o.cluster_id for o in page if o.cluster_id}
    if cids:
        for c in db.query(AIPromptCluster).filter(AIPromptCluster.id.in_(cids)).all():
            cluster_labels[c.id] = c.label

    return {
        "property_id": property_id,
        "metric": metric,
        "description": description,
        "window_days": days,
        "numerator": len(counting),
        "denominator": len(obs),
        "showing": "counting" if only_counting else "all",
        "total": len(rows),
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "observation_id": o.id,
                "response_id": o.response_id,
                "counts": _passes(o, key),
                "observed_at": o.observed_at.isoformat(),
                "platform": o.platform,
                "prompt": prompts.get(o.response_id, ("", ""))[0],
                "cluster": cluster_labels.get(o.cluster_id),
                "mentioned": o.mentioned,
                "mention_rank": o.mention_rank,
                "cited": o.cited,
                "recommended": o.recommended,
                "sentiment": o.sentiment,
                "competitors_named": o.competitor_mentioned_count,
                "excerpt": o.context_excerpt,
                "answer": (prompts.get(o.response_id, ("", ""))[1] or "")[:1500],
                "citations": cites.get(o.response_id, []),
            }
            for o in page
        ],
    }
