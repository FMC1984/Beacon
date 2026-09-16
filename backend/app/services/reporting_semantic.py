"""Semantic Intelligence report: topic coverage across sources.

For each topic in the shared 17-topic taxonomy, this asks the same question
of four independent sources and shows where they disagree:

  site content   what the property says about itself
  reviews        what residents say, with clause-scoped sentiment
  AI answers     what AI platforms said in Beacon's monitored runs
  search         what people actually typed into Google (Search Console)

The gaps between those columns are the point. A topic residents praise that
the site never mentions is a content gap; a topic people search for that the
site is silent on is a demand gap; a topic residents complain about that the
site markets loudly is a mismatch worth knowing before a prospect finds it.

Why this is buildable now: it was deferred with Phase 15c, whose blocker was
SIMILARITY CLUSTERING (it needs volume to cluster meaningfully). This report
needs no clustering. It uses the fixed, deterministic taxonomy that already
tags every RAG chunk, so nothing here waits on data volume, and 15c's
clustering stays honestly deferred in `deferred`.

Everything is deterministic: same inputs, same output, and each topic row
carries the matched evidence that put it there. Nothing is inferred from a
source the property does not have; a missing source is a named state, never
an implied zero.
"""

import re
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    AIPropertyObservation,
    AIVisibilityQuery,
    GSCPerformanceDaily,
    Property,
    PropertyContent,
    PropertyReview,
)
from app.services.reporting import DataState
from app.services.semantic.enrichment import _topic_sentiment
from app.services.semantic.text import load_reference

# A topic needs this many review mentions before its sentiment is characterized.
MIN_REVIEWS_FOR_SENTIMENT = 2
# Below this many search impressions a topic is present but not "demand".
MIN_IMPRESSIONS_FOR_DEMAND = 25
WINDOW_DAYS = 90
MAX_EVIDENCE = 3

SOURCE_LABELS = {
    "content": "Site content",
    "reviews": "Reviews",
    "ai_answers": "AI answers",
    "search": "Search Console",
}

DEFERRED = [
    "Similarity clustering and knowledge-base consolidation (Phase 15c) - this "
    "report uses the fixed taxonomy, so it does not wait on clustering, but "
    "grouping near-duplicate phrasings still does.",
]

LIMITATIONS = [
    "Topic tagging is deterministic keyword and phrase matching with negation "
    "handling, not a language model. It misses phrasings outside the taxonomy "
    "rather than guessing at them.",
    "Sentiment is clause-scoped and lexicon-based. It reports the words used, "
    "not the writer's feelings.",
    "Search Console shows what people typed into Google. It says nothing about "
    "what they asked an AI assistant.",
    "A search gap needs queries that are genuinely about the topic (a phrase, "
    "or two of its terms). A generic query that merely contains one term, like "
    "\"apartments for rent\" for pricing, is counted but does not raise a gap.",
]


def _topics() -> list[dict]:
    return load_reference("semantic_topics.json")["topics"]


def _match(text: str, terms: list[str]) -> list[str]:
    """Negation-aware presence: 'no maintenance issues' is not a maintenance
    mention, while 'no parking' still is (the shared negation rules decide)."""
    from app.services.semantic import match_with_negation

    res = match_with_negation(text or "", terms)
    return sorted(set(res.clean))


def _content_column(pages: list[PropertyContent], terms: list[str]) -> dict:
    hits, matched = [], set()
    for page in pages:
        found = _match(f"{page.title or ''} {page.body or ''}", terms)
        if found:
            hits.append(page.page)
            matched.update(found)
    return {"present": bool(hits), "pages": sorted(hits), "mentions": len(hits),
            "matched_terms": sorted(matched)[:6]}


def _reviews_column(reviews: list[PropertyReview], terms: list[str]) -> dict:
    mentions, sentiments, quote = 0, [], None
    for review in reviews:
        body = review.body or ""
        if not _match(body, terms):
            continue
        mentions += 1
        label = _topic_sentiment(body, [t.lower() for t in terms])
        sentiments.append(label)
        if quote is None or label == "negative":
            quote = " ".join(body.split())[:220]
    counts = {k: sentiments.count(k) for k in ("positive", "negative", "mixed", "neutral")}
    characterized = mentions >= MIN_REVIEWS_FOR_SENTIMENT
    # "Mixed" means both directions were actually found. When the lexicon
    # matched nothing either way the honest answer is no lean at all, not a
    # verdict of mixed: plenty of real complaints use words it does not know.
    lean = None
    if characterized and (counts["positive"] or counts["negative"]):
        if counts["negative"] > counts["positive"]:
            lean = "negative"
        elif counts["positive"] > counts["negative"]:
            lean = "positive"
        else:
            lean = "mixed"
    return {
        "present": mentions > 0, "mentions": mentions, "sentiment": counts,
        "lean": lean, "sentiment_detected": bool(counts["positive"] or counts["negative"]),
        "sample_quote": quote,
        "state": DataState.COMPLETE.value if characterized else DataState.INSUFFICIENT_SAMPLE.value,
        "minimum_sample": MIN_REVIEWS_FOR_SENTIMENT,
    }


def _ai_column(answers: list[str], terms: list[str]) -> dict:
    hits = sum(1 for text in answers if _match(text, terms))
    return {"present": hits > 0, "responses": hits, "of_responses": len(answers)}


def _query_terms(query: str, terms: list[str]) -> list[str]:
    """Whole-word matches, so 'fee' does not fire on 'coffee'."""
    lowered = (query or "").lower()
    return [t for t in terms if re.search(rf"\b{re.escape(t.lower())}\b", lowered)]


def _is_specific(matched: list[str]) -> bool:
    """Is this query really ABOUT the topic, or does it merely contain one of
    its words? "apartments for rent" contains the pricing term "rent" but is a
    generic discovery search; "rent increase" or a query hitting two pricing
    terms is genuinely about pricing. Gaps are claims about a property, so
    they need the stronger signal: a miss is fine, an invented finding is not.
    """
    return len(matched) >= 2 or any(" " in t for t in matched)


def _search_column(rows: list[tuple[str, int, int]], terms: list[str]) -> dict:
    impressions = clicks = specific_impressions = 0
    queries: list[dict] = []
    for query, imps, clks in rows:
        matched = _query_terms(query, terms)
        if not matched:
            continue
        specific = _is_specific(matched)
        impressions += imps
        clicks += clks
        if specific:
            specific_impressions += imps
        queries.append({"query": query, "impressions": imps, "clicks": clks,
                        "matched_terms": matched, "specific": specific})
    queries.sort(key=lambda q: (not q["specific"], -q["impressions"]))
    return {
        "present": impressions > 0, "impressions": impressions, "clicks": clicks,
        "specific_impressions": specific_impressions,
        "is_demand": specific_impressions >= MIN_IMPRESSIONS_FOR_DEMAND,
        "top_queries": queries[:MAX_EVIDENCE],
        "minimum_impressions": MIN_IMPRESSIONS_FOR_DEMAND,
    }


def _gap(topic: dict, row: dict, available: dict) -> dict | None:
    """One stated gap per topic, most actionable first. Only raised when the
    sources it compares are both actually present for this property."""
    label = topic["label"]
    content, reviews, ai, search = row["content"], row["reviews"], row["ai_answers"], row["search"]

    if available["search"] and search["is_demand"] and not content["present"]:
        top = ", ".join(q["query"] for q in search["top_queries"] if q["specific"]) or "topic queries"
        return {
            "type": "demand_gap", "topic": topic["key"], "topic_label": label,
            "headline": f"People search for {label.lower()} but the site does not cover it",
            "evidence": [
                f"{search['specific_impressions']} Search Console impressions on queries like {top}",
                "No page mentions this topic",
            ],
            "state": DataState.COMPLETE.value,
        }
    if available["reviews"] and reviews["present"] and not content["present"]:
        return {
            "type": "content_gap", "topic": topic["key"], "topic_label": label,
            "headline": f"Residents talk about {label.lower()} but the site does not",
            "evidence": [f"{reviews['mentions']} review(s) mention it"]
                        + ([f"“{reviews['sample_quote']}”"] if reviews["sample_quote"] else []),
            "state": DataState.COMPLETE.value,
        }
    if available["reviews"] and reviews["lean"] == "negative" and content["present"]:
        return {
            "type": "mismatch", "topic": topic["key"], "topic_label": label,
            "headline": f"The site markets {label.lower()} while reviews lean negative on it",
            "evidence": [f"{reviews['sentiment']['negative']} negative of {reviews['mentions']} review mention(s)",
                         f"Covered on: {', '.join(content['pages'])}"]
                        + ([f"“{reviews['sample_quote']}”"] if reviews["sample_quote"] else []),
            "state": DataState.COMPLETE.value,
        }
    if available["ai_answers"] and ai["present"] and not content["present"]:
        return {
            "type": "ai_gap", "topic": topic["key"], "topic_label": label,
            "headline": f"AI answers raise {label.lower()} and the site is silent on it",
            "evidence": [f"Mentioned in {ai['responses']} of {ai['of_responses']} monitored answers"],
            "state": DataState.COMPLETE.value,
        }
    return None


def build_semantic_report(db: Session, property_id: int | None, today: date | None = None) -> dict:
    if property_id is None:
        return {
            "scope_required": True,
            "message": "Select a single property to view its Semantic Intelligence report.",
        }
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    today = today or date.today()
    start = today - timedelta(days=WINDOW_DAYS - 1)

    pages = db.query(PropertyContent).filter_by(property_id=property_id).all()
    reviews = db.query(PropertyReview).filter_by(property_id=property_id).all()
    response_ids = [
        rid for (rid,) in db.query(AIPropertyObservation.response_id)
        .filter(AIPropertyObservation.property_id == property_id,
                AIPropertyObservation.eligible.is_(True))
        .distinct()
    ]
    answers = [
        text for (text,) in db.query(AIVisibilityQuery.raw_response_text)
        .filter(AIVisibilityQuery.id.in_(response_ids)).all()
    ] if response_ids else []
    search_rows = db.query(
        GSCPerformanceDaily.query,
        func.sum(GSCPerformanceDaily.impressions),
        func.sum(GSCPerformanceDaily.clicks),
    ).filter(
        GSCPerformanceDaily.property_id == property_id,
        GSCPerformanceDaily.date >= start,
        GSCPerformanceDaily.query.isnot(None),
    ).group_by(GSCPerformanceDaily.query).all()

    available = {"content": bool(pages), "reviews": bool(reviews),
                 "ai_answers": bool(answers), "search": bool(search_rows)}
    sources = [
        {"key": "content", "label": SOURCE_LABELS["content"], "documents": len(pages),
         "state": (DataState.COMPLETE if pages else DataState.NOT_CONFIGURED).value,
         "note": "Imported site pages." if pages else "No site content imported for this property."},
        {"key": "reviews", "label": SOURCE_LABELS["reviews"], "documents": len(reviews),
         "state": (DataState.COMPLETE if reviews else DataState.NOT_CONFIGURED).value,
         "note": "Resident reviews." if reviews else "No reviews imported for this property."},
        {"key": "ai_answers", "label": SOURCE_LABELS["ai_answers"], "documents": len(answers),
         "state": (DataState.COMPLETE if answers else DataState.AWAITING_DATA).value,
         "note": "Monitored AI responses this property was scored on."
                 if answers else "No monitored AI answers yet."},
        {"key": "search", "label": SOURCE_LABELS["search"], "documents": len(search_rows),
         "state": (DataState.COMPLETE if search_rows else DataState.NOT_CONFIGURED).value,
         "note": f"Search Console queries, last {WINDOW_DAYS} days."
                 if search_rows else "Search Console is not connected for this property."},
    ]

    topics_out, gaps = [], []
    for topic in _topics():
        terms = topic["terms"]
        row = {
            "key": topic["key"], "label": topic["label"],
            "content": _content_column(pages, terms),
            "reviews": _reviews_column(reviews, terms),
            "ai_answers": _ai_column(answers, terms),
            "search": _search_column(search_rows, terms),
        }
        # Only sources the property actually has can count toward coverage.
        signals = [k for k in SOURCE_LABELS if available[k] and row[k]["present"]]
        row["signal_sources"] = signals
        row["signal_count"] = len(signals)
        row["coverage_state"] = (
            "covered" if row["content"]["present"] and len(signals) > 1
            else "site_only" if row["content"]["present"]
            else "gap" if signals
            else "not_discussed"
        )
        topics_out.append(row)
        gap = _gap(topic, row, available)
        if gap:
            gaps.append(gap)

    discussed = [t for t in topics_out if t["signal_count"] > 0]
    covered = [t for t in topics_out if t["coverage_state"] == "covered"]
    return {
        "scope_required": False,
        "property_id": property_id,
        "property_name": prop.name,
        "generated_on": today.isoformat(),
        "window": {"start": start.isoformat(), "end": today.isoformat(), "days": WINDOW_DAYS},
        "taxonomy_version": load_reference("semantic_topics.json")["version"],
        "sources": sources,
        "has_data": any(available.values()),
        "summary": {
            "topics_total": len(topics_out),
            "topics_discussed": len(discussed),
            "topics_covered_on_site": len(covered),
            "sources_available": sum(1 for v in available.values() if v),
            "gaps": len(gaps),
        },
        "topics": topics_out,
        "gaps": gaps,
        "limitations": LIMITATIONS,
        "deferred": DEFERRED,
    }
