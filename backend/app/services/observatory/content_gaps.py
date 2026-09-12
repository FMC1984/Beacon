"""Content gaps from AI evidence (Phase 19, slice 6).

For each prompt cluster a property is subscribed to, over a window of
monitored answers:

  evidence   answers where the property was absent (MEASURED, from derived
             observations), domains those answers cited (OBSERVED), tracked
             competitors named without the property (OBSERVED)
  coverage   which of the topic's terms the property's own pages already use
             (the Content Intelligence whole-word matcher)
  action     one content change on one page, stated with its evidence

A gap needs a minimum sample, low visibility, and either a tracked competitor
winning or cited sources to learn from. Wording reports what the answers did;
it never promises that editing a page will change them. Every action is
passed through the Property Context gate before it is shown.
"""

from collections import Counter
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    AICitation,
    AIClusterVisibilityDaily,
    AIContentGap,
    AIPromptAssignment,
    AIPromptCluster,
    AIPropertyObservation,
    AIVisibilityPrompt,
    Competitor,
    Property,
    PropertyContent,
)
from app.services.ai_visibility.reference import MIN_QUERIES_FOR_VISIBILITY
from app.services.content_intelligence.matching import matched_terms
from app.services.jobs.queue import utcnow
from app.services.observatory.citations import domain_of_url
from app.services.observatory.taxonomy import topic as taxonomy_topic
from app.services.property_context import (
    REGULATED,
    SUPPRESSED,
    UNKNOWN,
    gate_text,
    get_property_context,
)

MAX_VISIBILITY = 0.34
EVIDENCE_RESPONSES = 10
PAGE_LABELS = {
    "homepage": "homepage", "amenities": "Amenities", "floor_plans": "Floor Plans",
    "neighborhood": "Neighborhood", "faq": "FAQ",
}
TOPIC_PAGE = {
    "amenities": "amenities", "pool": "amenities", "fitness_center": "amenities", "parking": "amenities",
    "garage": "amenities", "ev_charging": "amenities", "washer_dryer": "amenities", "dog_park": "amenities",
    "floor_plans": "floor_plans", "rent": "floor_plans", "specials": "floor_plans", "availability": "floor_plans",
    "neighborhoods": "neighborhood", "schools": "neighborhood", "transit": "neighborhood",
    "commuting": "neighborhood", "employers": "neighborhood", "walkability": "neighborhood",
    "pets": "faq", "breed_restrictions": "faq", "utilities": "faq", "move_in": "faq",
}
SENSITIVE_KEYWORDS = (
    "pricing", "price", "rent", "availab", "afford", "income", "eligib", "voucher", "special",
    "concession", "luxury", "student", "senior", "military", "exclusive",
)
REQUIRES_CONFIRMATION_MSG = (
    "This touches price, eligibility, or audience positioning. Confirm approved property messaging "
    "before acting on it."
)


def _window(days: int, today: date) -> tuple[datetime, datetime]:
    start = datetime.combine(today - timedelta(days=days - 1), datetime.min.time())
    return start, datetime.combine(today + timedelta(days=1), datetime.min.time())


def _gate(context: dict, text: str) -> tuple[str | None, str | None]:
    gt = gate_text(context, text)
    if gt.status == SUPPRESSED:
        return "Suppressed", gt.reason
    low = text.lower()
    if any(k in low for k in SENSITIVE_KEYWORDS) and context.get("effective_regulatory") in (UNKNOWN, REGULATED):
        return "Requires confirmation", REQUIRES_CONFIRMATION_MSG
    return None, None


def _page_coverage(pages: list[PropertyContent], terms: list[str], topic_key: str | None):
    best_page, best_hits = None, []
    covered: set[str] = set()
    for page in pages:
        hits = matched_terms(f"{page.title or ''} {page.body or ''}", terms)
        covered.update(hits)
        if len(hits) > len(best_hits):
            best_page, best_hits = page.page, hits
    target = best_page or TOPIC_PAGE.get(topic_key or "", "homepage")
    exists = any(p.page == target for p in pages)
    return target, exists, sorted(covered), [t for t in terms if t not in covered]


def _evidence(db: Session, property_id: int, cluster_id: int, start: datetime, end: datetime, owned: set[str]) -> dict:
    absent = (
        db.query(AIPropertyObservation)
        .filter(AIPropertyObservation.property_id == property_id, AIPropertyObservation.cluster_id == cluster_id,
                AIPropertyObservation.observed_at >= start, AIPropertyObservation.observed_at < end,
                AIPropertyObservation.mentioned.is_(False))
        .order_by(AIPropertyObservation.observed_at.desc())
        .all()
    )
    response_ids = [o.response_id for o in absent]
    domains: Counter = Counter()
    if response_ids:
        for dom, stype in db.query(AICitation.domain, AICitation.source_type).filter(AICitation.response_id.in_(response_ids)).all():
            if dom and not any(dom == d or dom.endswith("." + d) for d in owned):
                domains[(dom, stype)] += 1
    comp_ids: Counter = Counter()
    for o in absent:
        comp_ids.update(o.competitor_entity_ids or [])
    names = {c.id: c.name for c in db.query(Competitor).filter(Competitor.id.in_(list(comp_ids))).all()} if comp_ids else {}
    return {
        "absent_response_ids": response_ids[:EVIDENCE_RESPONSES],
        "absent_responses": len(response_ids),
        "cited_domains": [{"domain": d, "source_type": t, "citations": n} for (d, t), n in domains.most_common(5)],
        "competitors_named": [{"competitor_id": cid, "name": names.get(cid, "competitor"), "answers": n}
                              for cid, n in comp_ids.most_common(5)],
    }


def evaluate_gaps(db: Session, property_id: int, days: int = 30, today: date | None = None) -> dict:
    today = today or date.today()
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    start, end = _window(days, today)
    context = get_property_context(db, property_id)
    pages = db.query(PropertyContent).filter_by(property_id=property_id).all()
    owned = {d for d in [prop.domain or domain_of_url(prop.website_url)] if d}
    now = utcnow()
    cluster_ids = [cid for (cid,) in db.query(AIPromptAssignment.cluster_id).filter(
        AIPromptAssignment.property_id == property_id, AIPromptAssignment.active.is_(True),
        AIPromptAssignment.cluster_id.isnot(None)).distinct().all()]
    qualifying: set[str] = set()
    written = 0
    for cluster in db.query(AIPromptCluster).filter(AIPromptCluster.id.in_(cluster_ids)).order_by(AIPromptCluster.id).all() if cluster_ids else []:
        eligible, mentioned, wins = db.query(
            func.coalesce(func.sum(AIClusterVisibilityDaily.eligible_count), 0),
            func.coalesce(func.sum(AIClusterVisibilityDaily.mentioned_count), 0),
            func.coalesce(func.sum(AIClusterVisibilityDaily.competitor_win_count), 0),
        ).filter(AIClusterVisibilityDaily.property_id == property_id, AIClusterVisibilityDaily.cluster_id == cluster.id,
                 AIClusterVisibilityDaily.day >= start.date(), AIClusterVisibilityDaily.day <= today).one()
        if eligible < MIN_QUERIES_FOR_VISIBILITY:
            continue
        visibility = mentioned / eligible
        if visibility > MAX_VISIBILITY:
            continue
        ev = _evidence(db, property_id, cluster.id, start, end, owned)
        if not wins and not ev["cited_domains"]:
            continue  # nothing observed to learn from
        prompt = db.get(AIVisibilityPrompt, cluster.representative_prompt_id) if cluster.representative_prompt_id else None
        question = prompt.prompt_text if prompt else cluster.label
        t = taxonomy_topic(cluster.topic_key or "") or {}
        terms = list(t.get("terms") or [])
        key = f"{property_id}:{cluster.id}"
        qualifying.add(key)

        page_label = None
        if not pages:
            state, gate_reason = "Insufficient data", "No site content is imported, so Beacon cannot tell what the pages already cover."
            target, exists, covered, missing = TOPIC_PAGE.get(cluster.topic_key or "", "homepage"), False, [], terms
        else:
            target, exists, covered, missing = _page_coverage(pages, terms, cluster.topic_key)
            state, gate_reason = "Actionable", None
        page_label = PAGE_LABELS.get(target, target)
        domains = ", ".join(d["domain"] for d in ev["cited_domains"][:3]) or "no web sources"
        comps = ", ".join(c["name"] for c in ev["competitors_named"][:3])
        base = (f"In {eligible} monitored answers to this question, {prop.name} appeared in {mentioned}"
                + (f"; tracked competitors appeared without it in {wins} ({comps})" if wins else "")
                + f". Those answers cited {domains}.")
        if missing:
            title = f'Answer "{question}" on the {page_label} page' if exists else f'Add a {page_label} page that answers "{question}"'
            reason = base + f" The {page_label} page does not yet use: {', '.join(missing[:4])}."
            effort = "Low" if exists else "Medium"
        else:
            title = f'Strengthen how the {page_label} page answers "{question}"'
            reason = base + (f" The pages already use the topic's terms, so the gap may be in how directly the page answers "
                             f"the question or in coverage on the sources AI cites.")
            effort = "Medium"
        if state == "Actionable":
            g_state, g_reason = _gate(context, f"{title} {reason}")
            if g_state:
                state, gate_reason = g_state, g_reason
        impact = "High" if (cluster.importance or 3) >= 4 and mentioned == 0 else "Medium"
        row = db.query(AIContentGap).filter_by(gap_key=key).one_or_none()
        if row is None:
            row = AIContentGap(gap_key=key, property_id=property_id, cluster_id=cluster.id, first_detected=now,
                               organization_id=cluster.organization_id, status="open")
            db.add(row)
        elif row.status == "resolved":
            row.status = "open"
        row.topic_key, row.question, row.target_page, row.page_exists = cluster.topic_key, question, target, exists
        row.missing_terms, row.covered_terms, row.evidence = missing, covered, ev
        row.visibility, row.competitor_presence = round(visibility, 4), round(wins / eligible, 4)
        row.title, row.recommendation, row.state, row.gate_reason = title[:300], reason, state, gate_reason
        row.impact, row.effort, row.last_evaluated = impact, effort, now
        written += 1
    resolved = 0
    for row in db.query(AIContentGap).filter(AIContentGap.property_id == property_id, AIContentGap.status == "open").all():
        if row.gap_key not in qualifying:
            row.status, row.last_evaluated = "resolved", now
            resolved += 1
    db.commit()
    return {"property_id": property_id, "window_days": days, "gaps_open": written, "auto_resolved": resolved}


def gap_out(g: AIContentGap) -> dict:
    return {
        "id": g.id, "property_id": g.property_id, "cluster_id": g.cluster_id, "topic_key": g.topic_key,
        "question": g.question, "target_page": g.target_page, "page_exists": g.page_exists,
        "missing_terms": g.missing_terms or [], "covered_terms": g.covered_terms or [], "evidence": g.evidence or {},
        "visibility": g.visibility, "competitor_presence": g.competitor_presence, "title": g.title,
        "recommendation": g.recommendation, "state": g.state, "gate_reason": g.gate_reason, "impact": g.impact,
        "effort": g.effort, "status": g.status, "data_label": "MODELED",
        "first_detected": g.first_detected.isoformat() if g.first_detected else None,
        "last_evaluated": g.last_evaluated.isoformat() if g.last_evaluated else None,
    }


def gap_opportunities(db: Session, property_id: int) -> list[dict]:
    """Open gaps in the Opportunity Engine's recommendation shape, with
    citations back to the AI evidence and the page."""
    prop = db.get(Property, property_id)
    out = []
    for g in db.query(AIContentGap).filter_by(property_id=property_id, status="open").order_by(AIContentGap.id).all():
        ev = g.evidence or {}
        out.append({
            "title": g.title,
            "reason": g.recommendation,
            "state": g.state,
            "impact": g.impact,
            "effort": g.effort,
            "gate_reason": g.gate_reason,
            "citations": [{
                "property_id": property_id,
                "property_name": prop.name if prop else None,
                "page": g.target_page,
                "source_ref": f"ai_observatory: gap={g.id}, cluster={g.cluster_id}",
                "evidence": [
                    f"absent from {ev.get('absent_responses', 0)} monitored answers (responses {', '.join(map(str, ev.get('absent_response_ids', [])[:5]))})",
                    *[f"cited {d['domain']} ({d['citations']}x)" for d in ev.get("cited_domains", [])[:3]],
                ],
            }],
        })
    return out
