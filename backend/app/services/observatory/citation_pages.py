"""Top citation pages and "mentioned on page" (Phase 19).

Which specific pages AI answers cite for a property, ranked by share of all
citations in the window, and whether each page actually names the property.
That last column is the useful one: a directory page cited 40 times that
never mentions you is a listing gap you can act on; one that does mention
you is an asset worth keeping accurate.

The check has four honest states and never collapses them:
  mentioned      the page was fetched and names the property
  not_mentioned  the page was fetched and does not
  unchecked      Beacon has not fetched it yet (queue a check)
  unreachable    the fetch failed (blocked, timed out, not HTML), stated why
Only a successful fetch can produce "not mentioned"; a page Beacon could not
read is never reported as silent about the property.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import AICitation, AICitedPage, AIPropertyObservation, Competitor, Property
from app.models.ai_cited_pages import (
    CHECK_BLOCKED,
    CHECK_NOT_HTML,
    CHECK_OK,
    CHECK_UNREACHABLE,
    RECHECK_AFTER_DAYS,
)
from app.services.ai_visibility.mentions import resolve_property_terms
from app.services.ai_visibility.parsing import find_mention
from app.services.jobs.queue import utcnow
from app.services.observatory import LABEL_MEASURED, LABEL_OBSERVED, utc_today
from app.services.observatory.citations import competitor_domains_for, normalize_url, owned_domains_for
from app.services.observatory.observability import log_event

MAX_PAGES = 50
# How many uncached pages one check job will fetch, so a big portfolio never
# hammers other sites or ties up the runner.
CHECK_BATCH = 25

MENTIONED = "mentioned"
NOT_MENTIONED = "not_mentioned"
UNCHECKED = "unchecked"
UNREACHABLE = "unreachable"


def _bounds(days: int, today: date) -> tuple[datetime, datetime]:
    start = today - timedelta(days=days - 1)
    return datetime.combine(start, datetime.min.time()), datetime.combine(today + timedelta(days=1), datetime.min.time())


def _relabel(domain: str, owned: set[str], comp: set[str], stored: str | None) -> str | None:
    if any(domain == o or domain.endswith("." + o) for o in owned):
        return "owned"
    if any(domain == c or domain.endswith("." + c) for c in comp):
        return "competitor"
    return "property_site" if stored in ("owned", "competitor") else stored


def mention_state(page: AICitedPage | None, terms: list[str]) -> tuple[str, str | None]:
    """(state, detail). Never "not mentioned" without a readable page."""
    if page is None:
        return UNCHECKED, None
    if page.status != CHECK_OK:
        return UNREACHABLE, page.error or page.status
    hit = find_mention(page.body or "", terms)
    if hit:
        return MENTIONED, f"names it as \"{hit['term']}\" ({hit['count']}x)"
    return NOT_MENTIONED, None


def top_citation_pages(db: Session, property_id: int, days: int = 30, today: date | None = None,
                       limit: int = MAX_PAGES) -> dict:
    today = today or utc_today()
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    lo, hi = _bounds(days, today)
    response_ids = [
        rid for (rid,) in db.query(AIPropertyObservation.response_id)
        .filter(AIPropertyObservation.property_id == property_id, AIPropertyObservation.eligible.is_(True),
                AIPropertyObservation.observed_at >= lo, AIPropertyObservation.observed_at < hi)
        .distinct()
    ]
    if not response_ids:
        return {"property_id": property_id, "data_label": LABEL_OBSERVED, "total_citations": 0, "pages": [],
                "check": {"mentioned": 0, "not_mentioned": 0, "unchecked": 0, "unreachable": 0}}

    owned = owned_domains_for(prop)
    comp = competitor_domains_for(db.query(Competitor).filter_by(property_id=property_id).all())
    terms = resolve_property_terms(prop)
    agg: dict[str, dict] = defaultdict(lambda: {"citations": 0, "responses": set(), "url": None, "title": None,
                                                 "domain": None, "stored_type": None})
    for c in db.query(AICitation).filter(AICitation.response_id.in_(response_ids)).all():
        a = agg[c.normalized_url]
        a["citations"] += 1
        a["responses"].add(c.response_id)
        a["url"] = a["url"] or c.url
        a["title"] = a["title"] or c.title
        a["domain"] = c.domain
        a["stored_type"] = c.source_type
    total = sum(a["citations"] for a in agg.values())
    urls = list(agg)
    cached = {p.normalized_url: p for p in db.query(AICitedPage).filter(AICitedPage.normalized_url.in_(urls)).all()} if urls else {}

    pages = []
    check = {MENTIONED: 0, NOT_MENTIONED: 0, UNCHECKED: 0, UNREACHABLE: 0}
    for nurl, a in agg.items():
        page = cached.get(nurl)
        state, detail = mention_state(page, terms)
        check[state] += 1
        pages.append({
            "url": a["url"], "normalized_url": nurl, "domain": a["domain"], "title": a["title"] or (page.title if page else None),
            "source_type": _relabel(a["domain"], owned, comp, a["stored_type"]),
            "citations": a["citations"], "responses": len(a["responses"]),
            "share": round(a["citations"] / total, 4) if total else None,
            "mentioned_on_page": state, "mention_detail": detail,
            "checked_at": page.fetched_at.isoformat() if page else None,
        })
    pages.sort(key=lambda p: (-p["citations"], p["normalized_url"]))
    return {
        "property_id": property_id,
        "data_label": LABEL_OBSERVED,
        "mention_check_label": LABEL_MEASURED,
        "window_days": days,
        "total_citations": total,
        "distinct_pages": len(pages),
        "pages": pages[:limit],
        "check": check,
        "note": ("Citation counts are what providers reported. \"Mentioned on page\" is a text match over the "
                 "fetched page: a page Beacon could not read is shown as unreachable, never as silent."),
    }


def _store_fetch(db: Session, url: str, now: datetime) -> AICitedPage:
    from app.services.content_fetch import ContentFetchError, fetch_page_content

    normalized, domain, _root, _path = normalize_url(url)
    row = db.query(AICitedPage).filter_by(normalized_url=normalized).one_or_none()
    if row is None:
        row = AICitedPage(normalized_url=normalized, url=url, domain=domain, fetched_at=now, status=CHECK_UNREACHABLE)
        db.add(row)
    row.fetched_at, row.source, row.url = now, "fetch", url
    try:
        got = fetch_page_content(url)
    except ContentFetchError as exc:
        msg = str(exc)
        row.status = (CHECK_BLOCKED if "HTTP 4" in msg else CHECK_NOT_HTML if "did not return an HTML" in msg
                      else CHECK_UNREACHABLE)
        row.error, row.body, row.title, row.char_count = msg[:500], None, None, 0
        return row
    row.status, row.error = CHECK_OK, None
    row.title, row.body, row.char_count = (got["title"] or "")[:500], got["body"], got["char_count"]
    return row


def check_cited_pages(db: Session, property_id: int | None = None, days: int = 30, batch: int = CHECK_BATCH,
                      today: date | None = None) -> dict:
    """Fetch the most-cited pages that are unchecked or stale, most cited
    first, up to `batch`. Real network calls; run from the jobs runner."""
    today = today or utc_today()
    now = utcnow()
    stale_before = now - timedelta(days=RECHECK_AFTER_DAYS)
    props = db.query(Property).filter(Property.id == property_id) if property_id else db.query(Property).filter(Property.is_active.is_(True))
    # Sample properties cite real directory hosts with fictional paths; the
    # seeder stocks their cache rows, so they never trigger a real request.
    property_ids = [p.id for p in props if not (p.attributes or {}).get("sample_data")]
    wanted: dict[str, tuple[int, str]] = {}
    for pid in property_ids:
        for p in top_citation_pages(db, pid, days=days, today=today, limit=MAX_PAGES)["pages"]:
            if p["mentioned_on_page"] == UNCHECKED or (p["checked_at"] and datetime.fromisoformat(p["checked_at"]) < stale_before):
                prev = wanted.get(p["normalized_url"])
                wanted[p["normalized_url"]] = (max(p["citations"], prev[0] if prev else 0), p["url"])
    queue = sorted(wanted.items(), key=lambda kv: -kv[1][0])[:batch]
    fetched = ok = 0
    for _nurl, (_n, url) in queue:
        # Sample-domain and unresolvable hosts fail fast and are stored as unreachable.
        row = _store_fetch(db, url, now)
        fetched += 1
        ok += 1 if row.status == CHECK_OK else 0
        db.commit()
    log_event("cited_pages.checked", property_id=property_id, fetched=fetched, ok=ok, pending=max(0, len(wanted) - fetched))
    return {"fetched": fetched, "ok": ok, "pending": max(0, len(wanted) - fetched)}
