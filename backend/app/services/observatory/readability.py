"""AI readability v1: can a simple crawler read this property's site?

Fetches the property's homepage and a few of its own pages the way a plain
HTTP client does (no JavaScript executed), and reports:

  categories       which renter facts appear in that initial HTML: pricing,
                   availability, floor plans, pet policy, amenities, fees,
                   neighborhood, contact
  robots           whether robots.txt admits the AI crawlers, per agent
  structured data  JSON-LD types the pages declare (informational)
  findings         plain findings with a severity, from a stated rule

What v1 does not claim: that missing information is "hidden by JavaScript".
It says the fact is not present in the raw HTML a crawler receives, which
could mean a script renders it or that it is not published. Comparing raw
and rendered pages needs a headless browser and is a later version. Sample
properties are never fetched; the seeder stocks their checks.
"""

import json
import re
from datetime import date, datetime, timedelta
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.models import AIReadabilityCheck, Property, PropertyContent
from app.services.jobs.queue import utcnow
from app.services.observatory import LABEL_MEASURED
from app.services.observatory.observability import log_event
from app.services.observatory.tenancy import property_org_id

USER_AGENT = "Mozilla/5.0 (compatible; BeaconReadability/1.0; +internal tool)"
TIMEOUT = 15
MAX_PAGES = 5
MAX_TEXT = 40_000
RECHECK_AFTER_DAYS = 7

# The crawlers AI platforms publish. "unknown" when robots.txt is unreachable.
AI_AGENTS = ("GPTBot", "OAI-SearchBot", "ClaudeBot", "PerplexityBot", "Google-Extended", "Bingbot", "CCBot")

# Paths worth checking on a property site, matched against the site's own links.
PATH_HINTS = ("floorplan", "floor-plan", "amenit", "pet", "contact", "neighborhood", "pricing", "availab", "apply")

# Category detectors over visible text. Deliberately simple and stated.
CATEGORIES: dict[str, dict] = {
    "pricing": {"label": "Pricing", "severity": "critical",
                "pattern": r"\$\s?\d{1,2},?\d{3}\b|starting (?:at|from) \$|rent(?:s)? (?:from|start)"},
    "availability": {"label": "Availability", "severity": "critical",
                     "pattern": r"available now|availability|apply now|check availability|move-in ready|units? available"},
    "floor_plans": {"label": "Floor plans", "severity": "critical",
                    "pattern": r"floor ?plans?|\b(?:studio|one|two|three|1|2|3)[- ]?(?:bed|bedroom|br)\b"},
    "pets": {"label": "Pet policy", "severity": "high", "pattern": r"\bpets?\b|pet[- ]friendly|dogs?\b|cats?\b"},
    "amenities": {"label": "Amenities", "severity": "high",
                  "pattern": r"amenit|\bpool\b|fitness|\bgym\b|clubhouse|dog park|garage|in-unit|washer"},
    "fees": {"label": "Fees and deposits", "severity": "medium", "pattern": r"\bfees?\b|deposit|application fee|admin fee"},
    "neighborhood": {"label": "Neighborhood and location", "severity": "medium",
                     "pattern": r"neighborhood|minutes (?:from|to)|located|near(?:by)?\b|downtown|commute|walk(?:able|ing)"},
    "contact": {"label": "Contact information", "severity": "high",
                "pattern": r"\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b|[\w.+-]+@[\w-]+\.[\w.]+|contact us|schedule a tour"},
}


# A housing authority's site answers different questions: eligibility, how to
# apply, which programs and developments exist. Floor plans and pet policy are
# per development and are not expected on the authority's main site.
HA_CATEGORIES: dict[str, dict] = {
    "eligibility": {"label": "Eligibility and income limits", "severity": "critical",
                    "pattern": r"eligib|income limit|\bami\b|area median income|qualif"},
    "apply": {"label": "How to apply and waitlist", "severity": "critical",
              "pattern": r"\bapply\b|application|wait ?list|pre-?application|lottery"},
    "programs": {"label": "Programs offered", "severity": "high",
                 "pattern": r"program|housing choice|voucher|section 8|public housing|affordable|tax credit|lihtc"},
    "developments": {"label": "Developments and locations", "severity": "high",
                     "pattern": r"development|communities|properties|locations|apartments"},
    "neighborhood": CATEGORIES["neighborhood"],
    "contact": CATEGORIES["contact"],
}
HOUSING_AUTHORITY = "housing_authority"


def categories_for(prop: Property) -> dict[str, dict]:
    return HA_CATEGORIES if getattr(prop, "property_type", None) == HOUSING_AUTHORITY else CATEGORIES


def _fetch(client: httpx.Client, url: str) -> tuple[int | None, str | None, str | None]:
    """(http_status, html, error)."""
    try:
        r = client.get(url)
    except httpx.TimeoutException:
        return None, None, f"timed out after {TIMEOUT}s"
    except httpx.RequestError as exc:
        return None, None, f"could not reach: {exc.__class__.__name__}"
    if r.status_code >= 400:
        return r.status_code, None, f"HTTP {r.status_code}"
    if "html" not in r.headers.get("content-type", "").lower():
        return r.status_code, None, "not an HTML page"
    return r.status_code, r.text, None


def analyze_html(html: str, spec: dict[str, dict] | None = None) -> dict:
    """Pure: text a crawler sees without scripts, the link paths, JSON-LD types,
    script count, and which categories the text matches with evidence."""
    spec = spec or CATEGORIES
    soup = BeautifulSoup(html or "", "html.parser")
    scripts = len(soup.find_all("script"))
    types: list[str] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(tag.string or "")
        except (ValueError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            if isinstance(it, dict):
                t = it.get("@type")
                types += t if isinstance(t, list) else ([t] if t else [])
    links = [a.get("href") for a in soup.find_all("a", href=True)]
    for tag in soup.find_all(("script", "style", "noscript", "svg")):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(separator=" ", strip=True))[:MAX_TEXT]
    found: dict[str, str] = {}
    for key, cat in spec.items():
        m = re.search(cat["pattern"], text, re.IGNORECASE)
        if m:
            lo, hi = max(0, m.start() - 60), min(len(text), m.end() + 60)
            found[key] = text[lo:hi].strip()
    return {"text_chars": len(text), "scripts": scripts, "links": links, "jsonld_types": types, "found": found}


def _candidate_pages(db: Session, prop: Property, home: str, links: list[str]) -> list[str]:
    """Homepage first, then the property's known pages, then site links whose
    path looks like a renter-facts page. Same host only, capped."""
    host = urlsplit(home).netloc.lower().removeprefix("www.")
    out = [home]
    for row in db.query(PropertyContent).filter_by(property_id=prop.id).all():
        if row.source_url and row.source_url not in out:
            out.append(row.source_url)
    for href in links:
        if len(out) >= MAX_PAGES:
            break
        full = urljoin(home, href)
        parts = urlsplit(full)
        if parts.scheme not in ("http", "https") or parts.netloc.lower().removeprefix("www.") != host:
            continue
        if any(h in parts.path.lower() for h in PATH_HINTS) and full.split("#")[0] not in out:
            out.append(full.split("#")[0])
    return out[:MAX_PAGES]


def _robots(client: httpx.Client, home: str) -> dict:
    parts = urlsplit(home)
    url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        r = client.get(url)
    except httpx.HTTPError:
        return {"reachable": False, "url": url, "agents": {a: "unknown" for a in AI_AGENTS}}
    if r.status_code == 404:
        # No robots.txt means nothing is disallowed.
        return {"reachable": True, "url": url, "present": False, "agents": {a: "allowed" for a in AI_AGENTS}}
    if r.status_code >= 400:
        return {"reachable": False, "url": url, "agents": {a: "unknown" for a in AI_AGENTS}}
    rp = RobotFileParser()
    rp.parse(r.text.splitlines())
    return {"reachable": True, "url": url, "present": True,
            "agents": {a: ("allowed" if rp.can_fetch(a, home) else "disallowed") for a in AI_AGENTS}}


def build_findings(categories: dict, robots: dict, pages: list[dict], spec: dict[str, dict] | None = None) -> list[dict]:
    """Findings from a stated rule. With no readable pages, only the robots
    findings apply: an unreadable site says nothing about its content."""
    spec = spec or CATEGORIES
    out = []
    for key, cat in spec.items():
        if pages and not categories.get(key, {}).get("present"):
            out.append({
                "severity": cat["severity"], "category": key,
                "text": (f"{cat['label']}: not present in the raw HTML of the {len(pages)} page(s) checked. A crawler "
                         "that does not run JavaScript cannot read it there; it may be rendered by a script or not published."),
            })
    blocked = [a for a, s in robots.get("agents", {}).items() if s == "disallowed"]
    if blocked:
        out.append({"severity": "critical", "category": "robots",
                    "text": f"robots.txt disallows {', '.join(blocked)}. Those AI crawlers will not read the site at all."})
    if not robots.get("reachable"):
        out.append({"severity": "medium", "category": "robots",
                    "text": "robots.txt could not be read, so crawler permissions are unknown."})
    heavy = [p for p in pages if p.get("chars") is not None and p["chars"] < 400 and p.get("scripts", 0) >= 5]
    if heavy:
        out.append({"severity": "high", "category": "rendering",
                    "text": (f"{len(heavy)} page(s) deliver under 400 characters of text with 5 or more scripts: "
                             "most of what a visitor sees is likely rendered by JavaScript.")})
    order = {"critical": 0, "high": 1, "medium": 2}
    out.sort(key=lambda f: (order.get(f["severity"], 3), f["category"]))
    return out


def run_check(db: Session, property_id: int, now: datetime | None = None, client: httpx.Client | None = None) -> AIReadabilityCheck:
    """Real network calls; run from the jobs runner. Sample properties are
    never fetched."""
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    now = now or utcnow()
    org_id = property_org_id(db, property_id)
    home = (prop.website_url or "").strip()
    row = AIReadabilityCheck(organization_id=org_id, property_id=property_id, checked_at=now, site_url=home or "",
                             status="error", source="fetch")
    if (prop.attributes or {}).get("sample_data"):
        row.error = "Sample property: not fetched."
        db.add(row)
        db.commit()
        return row
    if not re.match(r"^https?://", home, re.IGNORECASE):
        row.error = "No website URL recorded for the property."
        db.add(row)
        db.commit()
        return row

    spec = categories_for(prop)
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT})
    try:
        status, html, err = _fetch(client, home)
        if html is None:
            row.error = f"Homepage {home}: {err}"
            row.robots = _robots(client, home)
            row.findings = build_findings({}, row.robots, [], spec)
            db.add(row)
            db.commit()
            return row
        first = analyze_html(html, spec)
        pages = [{"url": home, "http_status": status, "chars": first["text_chars"], "scripts": first["scripts"], "found": first["found"]}]
        types = list(first["jsonld_types"])
        for url in _candidate_pages(db, prop, home, first["links"])[1:]:
            st, h, e = _fetch(client, url)
            if h is None:
                pages.append({"url": url, "http_status": st, "chars": None, "scripts": 0, "found": {}, "error": e})
                continue
            a = analyze_html(h, spec)
            pages.append({"url": url, "http_status": st, "chars": a["text_chars"], "scripts": a["scripts"], "found": a["found"]})
            types += a["jsonld_types"]
        categories = {}
        for key in spec:
            hit = next((p for p in pages if p["found"].get(key)), None)
            categories[key] = {"present": hit is not None, "page": hit["url"] if hit else None,
                               "evidence": hit["found"][key] if hit else None}
        row.status, row.pages, row.categories = "ok", pages, categories
        row.robots = _robots(client, home)
        row.structured_data = sorted(set(types))
        row.findings = build_findings(categories, row.robots, pages, spec)
    finally:
        if own:
            client.close()
    db.add(row)
    db.commit()
    log_event("readability.checked", property_id=property_id, status=row.status, findings=len(row.findings or []))
    return row


def check_due(db: Session, now: datetime | None = None) -> dict:
    """Every active, non-sample property with a website whose latest check is
    older than RECHECK_AFTER_DAYS (or missing)."""
    now = now or utcnow()
    cutoff = now - timedelta(days=RECHECK_AFTER_DAYS)
    checked = 0
    for prop in db.query(Property).filter(Property.is_active.is_(True)).all():
        if (prop.attributes or {}).get("sample_data") or not prop.website_url:
            continue
        last = (db.query(AIReadabilityCheck).filter_by(property_id=prop.id)
                .order_by(AIReadabilityCheck.checked_at.desc()).first())
        if last is None or last.checked_at < cutoff:
            run_check(db, prop.id, now=now)
            checked += 1
    return {"checked": checked}


def readability_report(db: Session, property_id: int) -> dict:
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    row = (db.query(AIReadabilityCheck).filter_by(property_id=property_id)
           .order_by(AIReadabilityCheck.checked_at.desc()).first())
    base = {
        "property_id": property_id, "data_label": LABEL_MEASURED, "site_url": prop.website_url,
        "categories_spec": {k: {"label": v["label"], "severity": v["severity"]} for k, v in categories_for(prop).items()},
        "agents": list(AI_AGENTS),
        "note": ("Checked the way a plain crawler reads the site: no JavaScript run. A fact that is missing here may be "
                 "rendered by a script or not published; Beacon does not claim which. Comparing raw and rendered pages "
                 "is a later version."),
    }
    if row is None:
        return {**base, "checked": False, "reason": "Not checked yet." if prop.website_url else "No website URL recorded."}
    sev = {"critical": 0, "high": 0, "medium": 0}
    for f in row.findings or []:
        sev[f["severity"]] = sev.get(f["severity"], 0) + 1
    return {
        **base, "checked": True, "checked_at": row.checked_at.isoformat(), "status": row.status, "error": row.error,
        "is_sample": row.source == "sample", "pages": row.pages or [], "categories": row.categories or {},
        "robots": row.robots or {}, "structured_data": row.structured_data or [], "findings": row.findings or [],
        "summary": {**sev, "present": sum(1 for c in (row.categories or {}).values() if c.get("present")),
                    "total": len(categories_for(prop))},
    }
