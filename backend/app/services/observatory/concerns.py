"""Areas of concern: topic-level visibility gaps against the comp set.

For every topic the property is monitored on: its AI Visibility on that
topic, the best tracked competitor's, the gap in points, how much evidence
there is, and a concern level from a stated rule. Opening a topic explains
the gap from stored evidence only: how often the property was absent, which
competitors were named instead, which sources and pages those answers cited
and who is named on them, and what the property's own pages already say.

Rates are MEASURED. The concern level is a rule over them (thresholds below)
and is never a forecast: Beacon does not predict a lift from fixing anything.
"""

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import (
    AICitation,
    AICitedPage,
    AIContentGap,
    AIPromptCluster,
    AIPropertyObservation,
    Competitor,
    Property,
    PropertyContent,
)
from app.models.ai_cited_pages import CHECK_OK
from app.services.ai_visibility.mentions import resolve_competitor_terms, resolve_property_terms
from app.services.ai_visibility.parsing import find_mention
from app.services.ai_visibility.reference import MIN_QUERIES_FOR_VISIBILITY
from app.services.observatory import LABEL_MEASURED, utc_today
from app.services.observatory.citation_pages import _relabel
from app.services.observatory.citations import competitor_domains_for, owned_domains_for
from app.services.observatory.content_gaps import _gate, _page_coverage
from app.services.observatory.taxonomy import topic as taxonomy_topic
from app.services.property_context import get_property_context
from app.services.reporting import rate

HIGH_GAP = 0.20       # competitor ahead by 20 points or more
MEDIUM_GAP = 0.10
STRONG_EVIDENCE = 10  # answers
LOW_OWN = 0.25        # with no competitors tracked, own visibility below this is a high concern
MID_OWN = 0.50
GENERAL = "general"


def _label(key: str) -> str:
    t = taxonomy_topic(key) or {}
    return t.get("label") or key.replace("_", " ").capitalize()


def _observations(db: Session, property_id: int, days: int, today: date):
    lo = datetime.combine(today - timedelta(days=days - 1), datetime.min.time())
    hi = datetime.combine(today + timedelta(days=1), datetime.min.time())
    obs = (
        db.query(AIPropertyObservation)
        .filter(AIPropertyObservation.property_id == property_id, AIPropertyObservation.eligible.is_(True),
                AIPropertyObservation.cluster_id.isnot(None),
                AIPropertyObservation.observed_at >= lo, AIPropertyObservation.observed_at < hi)
        .all()
    )
    clusters = {}
    ids = {o.cluster_id for o in obs}
    if ids:
        clusters = {c.id: c for c in db.query(AIPromptCluster).filter(AIPromptCluster.id.in_(list(ids))).all()}
    by_topic: dict[str, list] = defaultdict(list)
    for o in obs:
        c = clusters.get(o.cluster_id)
        by_topic[(c.topic_key if c and c.topic_key else GENERAL)].append(o)
    return by_topic, clusters


def _level(sufficient: bool, mine: float | None, best: float | None, has_competitors: bool) -> str:
    if not sufficient or mine is None:
        return "insufficient"
    if has_competitors and best is not None:
        gap = mine - best
        if gap <= -HIGH_GAP:
            return "high"
        if gap <= -MEDIUM_GAP:
            return "medium"
        return "maintain" if gap >= MEDIUM_GAP else "monitor"
    return "high" if mine < LOW_OWN else "medium" if mine < MID_OWN else "maintain"


def areas_of_concern(db: Session, property_id: int, days: int = 30, today: date | None = None) -> dict:
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    today = today or utc_today()
    competitors = {c.id: c.name for c in db.query(Competitor).filter_by(property_id=property_id).all()}
    by_topic, _ = _observations(db, property_id, days, today)
    rows = []
    for key, obs in by_topic.items():
        n = len(obs)
        mine = rate(sum(1 for o in obs if o.mentioned), n, MIN_QUERIES_FOR_VISIBILITY)
        comp_counts: Counter = Counter()
        for o in obs:
            comp_counts.update(cid for cid in set(o.competitor_entity_ids or []) if cid in competitors)
        best_id, best_n = (comp_counts.most_common(1)[0] if comp_counts else (None, 0))
        best = rate(best_n, n, MIN_QUERIES_FOR_VISIBILITY) if competitors else None
        sufficient = mine["value"] is not None
        level = _level(sufficient, mine["value"], best["value"] if best else None, bool(competitors))
        gap = round(mine["value"] - best["value"], 4) if sufficient and best and best["value"] is not None else None
        rows.append({
            "topic_key": key, "label": _label(key), "answers": n,
            "visibility": mine,
            "best_competitor": ({"name": competitors.get(best_id), "rate": best} if best_id else None),
            "gap_points": gap,
            "evidence": "strong" if n >= STRONG_EVIDENCE else "medium" if n >= MIN_QUERIES_FOR_VISIBILITY else "weak",
            "concern": level,
            "absent": sum(1 for o in obs if not o.mentioned),
        })
    order = {"high": 0, "medium": 1, "monitor": 2, "maintain": 3, "insufficient": 4}
    rows.sort(key=lambda r: (order[r["concern"]], r["gap_points"] if r["gap_points"] is not None else 0, r["label"]))
    return {
        "property_id": property_id, "data_label": LABEL_MEASURED,
        "window": {"start": (today - timedelta(days=days - 1)).isoformat(), "end": today.isoformat(), "days": days},
        "tracked_competitors": len(competitors),
        "topics": rows,
        "summary": {k: sum(1 for r in rows if r["concern"] == k) for k in order},
        "rule": {"high_gap_points": HIGH_GAP, "medium_gap_points": MEDIUM_GAP, "strong_evidence_answers": STRONG_EVIDENCE,
                 "minimum_sample": MIN_QUERIES_FOR_VISIBILITY},
        "note": ("Visibility is the share of monitored answers on the topic that name you; the comparison is the single "
                 "tracked competitor named most often on that topic. Concern levels follow a stated rule and are not "
                 "forecasts."),
    }


def explain_concern(db: Session, property_id: int, topic_key: str, days: int = 30, today: date | None = None) -> dict:
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    today = today or utc_today()
    by_topic, clusters = _observations(db, property_id, days, today)
    obs = by_topic.get(topic_key)
    if not obs:
        raise LookupError("No monitored answers for this topic in the window.")
    competitors = db.query(Competitor).filter_by(property_id=property_id).all()
    comp_names = {c.id: c.name for c in competitors}
    owned, comp_domains = owned_domains_for(prop), competitor_domains_for(competitors)
    n = len(obs)
    absent = [o for o in obs if not o.mentioned]

    winners: Counter = Counter()
    for o in absent:
        winners.update(cid for cid in set(o.competitor_entity_ids or []) if cid in comp_names)

    domains: Counter = Counter()
    pages: Counter = Counter()
    stored: dict[str, str | None] = {}
    rids = [o.response_id for o in absent]
    if rids:
        for c in db.query(AICitation).filter(AICitation.response_id.in_(rids)).all():
            domains[c.domain] += 1
            pages[c.normalized_url] += 1
            stored[c.domain] = c.source_type
    cached = {p.normalized_url: p for p in db.query(AICitedPage).filter(AICitedPage.normalized_url.in_(list(pages))).all()} if pages else {}
    prop_terms = resolve_property_terms(prop)
    page_rows = []
    for nurl, cnt in pages.most_common(5):
        page = cached.get(nurl)
        readable = page is not None and page.status == CHECK_OK
        page_rows.append({
            "url": nurl, "citations": cnt,
            "read": readable,
            "names_you": bool(find_mention(page.body or "", prop_terms)) if readable else None,
            "names_competitors": sorted(c.name for c in competitors if readable and find_mention(page.body or "", resolve_competitor_terms(c))),
        })

    t = taxonomy_topic(topic_key) or {}
    terms = list(t.get("terms") or [])
    site_pages = db.query(PropertyContent).filter_by(property_id=property_id).all()
    target, exists, covered, missing = _page_coverage(site_pages, terms, topic_key) if terms else ("homepage", bool(site_pages), [], [])

    gaps = (
        db.query(AIContentGap)
        .filter(AIContentGap.property_id == property_id, AIContentGap.status == "open", AIContentGap.topic_key == topic_key)
        .all()
    )
    label = _label(topic_key)
    if gaps:
        action = gaps[0].recommendation
    elif not site_pages:
        action = f"Add the property's own pages to Beacon so it can compare what the site says about {label.lower()} with what AI answers cite."
    elif missing and not covered:
        action = f"Your site does not cover {label.lower()} in the terms renters use. Add verified {label.lower()} information to the {target} page."
    elif missing:
        action = f"Your {target} page covers part of this. Add verified detail on: {', '.join(missing[:4])}."
    else:
        action = f"Your site already covers {label.lower()}. The gap is off-site: see which cited pages below do not name you."
    state, gate_reason = _gate(get_property_context(db, property_id), f"{label} {action}")

    sentences = [f"You were absent from {len(absent)} of {n} monitored answers about {label.lower()}."]
    for cid, cnt in winners.most_common(3):
        sentences.append(f"{comp_names[cid]} was named in {cnt} of the answers that left you out.")
    silent = [p for p in page_rows if p["read"] and p["names_you"] is False]
    if silent:
        sentences.append(f"{len(silent)} of the most-cited pages in those answers do not name you: {', '.join(p['url'] for p in silent[:3])}.")
    if terms:
        sentences.append(
            f"Your own pages mention {len(covered)} of {len(terms)} {label.lower()} terms"
            + (f" (missing: {', '.join(missing[:4])})." if missing else ".")
        )
    return {
        "property_id": property_id, "topic_key": topic_key, "label": label, "data_label": LABEL_MEASURED,
        "answers": n, "absent": len(absent), "absent_response_ids": rids[:10],
        "questions": sorted({clusters[o.cluster_id].label for o in obs if o.cluster_id in clusters})[:6],
        "competitors_winning": [{"name": comp_names[cid], "answers": cnt} for cid, cnt in winners.most_common(5)],
        "cited_sources": [{"domain": d, "citations": c, "source_type": _relabel(d, owned, comp_domains, stored.get(d))}
                          for d, c in domains.most_common(5)],
        "cited_pages": page_rows,
        "own_content": {"pages": len(site_pages), "target_page": target, "target_exists": exists,
                        "covered_terms": covered, "missing_terms": missing},
        "explanation": sentences,
        "recommended_action": {"text": action, "state": state or "Actionable", "gate_reason": gate_reason,
                               "from_content_gap": bool(gaps)},
        "note": "Every line comes from stored answers, fetched pages and your own content. Nothing here is a forecast.",
    }
