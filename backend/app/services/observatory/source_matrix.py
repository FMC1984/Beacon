"""Source Influence Matrix: where AI learns about this property.

One row per domain AI answers cited for the property's questions, with:
  influence            share of citations (MEASURED), tiered by a stated rule
  property presence    from the cited pages Beacon fetched: present, absent,
                       or unknown (unchecked or unreachable, never "absent")
  competitor advantage tracked competitors named on those same pages when
                       the property is not
  by platform          the domain's share within each platform's citations
  action               a stated rule over the columns above

The accuracy column is deliberately empty: whether a source's facts are right
needs the Truth layer, and Beacon does not grade what it has not compared.
"""

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import AICitation, AICitedPage, AIPropertyObservation, Competitor, Property
from app.models.ai_cited_pages import CHECK_OK
from app.services.ai_visibility.mentions import resolve_competitor_terms, resolve_property_terms
from app.services.ai_visibility.parsing import find_mention
from app.services.observatory import LABEL_MEASURED, utc_today
from app.services.observatory.citation_pages import _relabel
from app.services.observatory.citations import competitor_domains_for, owned_domains_for

HIGH_INFLUENCE = 0.15
MEDIUM_INFLUENCE = 0.05

ACTIONS = {
    "expand": "Your own site is a leading source. Keep it complete and current.",
    "strengthen": "Your own site is rarely cited. Make the facts renters ask about easy to find on it.",
    "study": "A competitor's own site is being cited. See what it answers that yours does not.",
    "fix": "An influential source that does not mention you. Claim or update the listing.",
    "opportunity": "A minor source that does not mention you. Worth a listing when convenient.",
    "maintain": "An influential source that names you. Keep its facts accurate.",
    "monitor": "A minor source that names you. No action needed.",
    "check": "Beacon has not read this source's cited pages yet. Queue a page check.",
    "verify": "Beacon could not read this source's pages (blocked or down). Check it by hand.",
}


def _tier(share: float) -> str:
    return "high" if share >= HIGH_INFLUENCE else "medium" if share >= MEDIUM_INFLUENCE else "low"


def source_matrix(db: Session, property_id: int, days: int = 30, today: date | None = None, limit: int = 25) -> dict:
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    today = today or utc_today()
    start = today - timedelta(days=days - 1)
    lo = datetime.combine(start, datetime.min.time())
    hi = datetime.combine(today + timedelta(days=1), datetime.min.time())
    competitors = db.query(Competitor).filter_by(property_id=property_id).all()
    owned, comp_domains = owned_domains_for(prop), competitor_domains_for(competitors)
    prop_terms = resolve_property_terms(prop)
    comp_terms = {c.name: resolve_competitor_terms(c) for c in competitors}

    rows = (
        db.query(AICitation.domain, AICitation.source_type, AICitation.normalized_url, AIPropertyObservation.platform)
        .join(AIPropertyObservation, AIPropertyObservation.response_id == AICitation.response_id)
        .filter(AIPropertyObservation.property_id == property_id, AIPropertyObservation.eligible.is_(True),
                AIPropertyObservation.observed_at >= lo, AIPropertyObservation.observed_at < hi)
        .all()
    )
    total = len(rows)
    if not total:
        return {"property_id": property_id, "data_label": LABEL_MEASURED, "total_citations": 0, "sources": [],
                "platforms": [], "actions": ACTIONS, "window": {"start": start.isoformat(), "end": today.isoformat(), "days": days}}

    agg: dict[str, dict] = defaultdict(lambda: {"citations": 0, "stored_type": None, "urls": Counter(), "platforms": Counter()})
    platform_totals: Counter = Counter()
    for domain, stype, nurl, platform in rows:
        a = agg[domain]
        a["citations"] += 1
        a["stored_type"] = stype
        a["urls"][nurl] += 1
        a["platforms"][platform] += 1
        platform_totals[platform] += 1
    all_urls = [u for a in agg.values() for u in a["urls"]]
    cached = {p.normalized_url: p for p in db.query(AICitedPage).filter(AICitedPage.normalized_url.in_(all_urls)).all()}

    out = []
    for domain, a in agg.items():
        share = a["citations"] / total
        stype = _relabel(domain, owned, comp_domains, a["stored_type"])
        readable = [cached[u] for u in a["urls"] if u in cached and cached[u].status == CHECK_OK]
        unreachable = [u for u in a["urls"] if u in cached and cached[u].status != CHECK_OK]
        named = any(find_mention(p.body or "", prop_terms) for p in readable)
        rivals = sorted({name for p in readable for name, terms in comp_terms.items() if find_mention(p.body or "", terms)})
        if stype == "owned":
            presence = "owned"
        elif readable:
            presence = "present" if named else "absent"
        else:
            presence = "unknown"
        if stype == "competitor":
            advantage = "high"
        elif not readable:
            advantage = "unknown"
        elif rivals and not named:
            advantage = "high"
        elif rivals:
            advantage = "shared"
        else:
            advantage = "none"
        tier = _tier(share)
        if stype == "owned":
            action = "expand" if tier != "low" else "strengthen"
        elif stype == "competitor":
            action = "study"
        elif presence == "absent":
            action = "fix" if tier != "low" else "opportunity"
        elif presence == "present":
            action = "maintain" if tier != "low" else "monitor"
        else:
            action = "verify" if unreachable and len(unreachable) == len(a["urls"]) else "check"
        out.append({
            "domain": domain, "source_type": stype, "citations": a["citations"], "share": round(share, 4),
            "influence": tier, "presence": presence,
            "pages": {"cited": len(a["urls"]), "read": len(readable), "unreachable": len(unreachable)},
            "competitors_named": rivals, "competitor_advantage": advantage,
            "accuracy": None,
            "by_platform": {pl: round(n / platform_totals[pl], 4) for pl, n in a["platforms"].items()},
            "action": action, "action_text": ACTIONS[action],
        })
    out.sort(key=lambda r: (-r["citations"], r["domain"]))
    return {
        "property_id": property_id, "data_label": LABEL_MEASURED,
        "window": {"start": start.isoformat(), "end": today.isoformat(), "days": days},
        "total_citations": total, "distinct_sources": len(out), "sources": out[:limit],
        "platforms": sorted(platform_totals),
        "thresholds": {"high": HIGH_INFLUENCE, "medium": MEDIUM_INFLUENCE},
        "actions": ACTIONS,
        "accuracy_note": "Whether each source's facts are correct is not graded yet; that needs recorded facts compared per source.",
        "note": ("Influence is the source's share of citations. Presence and competitor advantage come only from cited "
                 "pages Beacon fetched and could read; an unread source is unknown, never absent."),
    }
