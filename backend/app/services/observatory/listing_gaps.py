"""Listing gaps as Opportunity Engine actions (flow P1).

A directory page AI answers keep citing for this property's questions, that
Beacon fetched and found does not name the property, is the most concrete
thing a leasing team can fix this week: claim or update the listing. The
action carries the page, how often it was cited, and when the mention check
ran. Pages Beacon has not fetched, or could not read, never become actions;
there is no evidence yet that anything is missing.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.models import Property
from app.services.observatory.citation_pages import NOT_MENTIONED, top_citation_pages

# Fewer citations than this and the page is not yet a pattern worth a task.
MIN_CITATIONS = 3
HIGH_IMPACT_CITATIONS = 10
ACTIONABLE_TYPES = {"directory", "ils", "review_site", "news", "forum", "other", None}


def listing_gap_opportunities(db: Session, property_id: int, days: int = 30, today: date | None = None) -> list[dict]:
    prop = db.get(Property, property_id)
    if prop is None:
        return []
    pages = top_citation_pages(db, property_id, days=days, today=today, limit=50)
    out = []
    for p in pages["pages"]:
        if p["mentioned_on_page"] != NOT_MENTIONED or p["citations"] < MIN_CITATIONS:
            continue
        if p["source_type"] not in ACTIONABLE_TYPES:
            continue  # owned or competitor pages are not listing gaps
        out.append({
            "title": f"Get {prop.name} onto {p['domain']}: the cited page does not mention it",
            "reason": (
                f"{p['normalized_url']} is cited in {p['citations']} monitored AI answer(s) about this property's "
                f"questions ({p['responses']} answers) and Beacon read the page without finding the property's name. "
                "Claim or update the listing so the page names the property; an answer that cites this page cannot "
                "recommend the property from it."
            ),
            "state": "Actionable",
            "impact": "High" if p["citations"] >= HIGH_IMPACT_CITATIONS else "Medium",
            "effort": "Low",
            "evidence_level": "MEASURED",
            "citations": [{
                "property_id": property_id,
                "property_name": prop.name,
                "page": p["url"],
                "source_ref": f"ai_observatory: listing_gap={p['normalized_url']}",
                "evidence": [
                    f"cited {p['citations']} time(s) in {p['responses']} monitored answer(s), last {days} days",
                    f"page fetched {p['checked_at'][:10] if p['checked_at'] else 'unknown'}: no mention of "
                    f"\"{prop.name}\" or its aliases",
                ],
            }],
        })
    return out
