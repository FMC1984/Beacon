"""Property setup checklist.

Six steps, in the order the rest of Beacon depends on them. Each step is a
deterministic check over rows that already exist; nothing here is inferred.
The checklist is what the property dashboard, the AI Visibility section and
Reports show instead of an unexplained empty state: which step is missing,
what it unlocks, and where to do it.

Steps are ordered by dependency, not importance. Identity feeds the market
and owned-domain matching; data feeds Reports; facts gate recommendations
and verify AI claims; competitors give Share of Voice a denominator; prompts
start monitoring; monitoring produces the first observations.
"""

from dataclasses import dataclass, field

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    AIPropertyObservation,
    AIVisibilityPrompt,
    Competitor,
    CRMLead,
    DataConnection,
    GA4SessionsDaily,
    GBPMetricsDaily,
    GSCPerformanceDaily,
    Property,
    PropertyContent,
    PropertyProfile,
    PropertyReview,
)
from app.models.connections import OAuthStatus
from app.services.observatory.assignments import assignments_for_property

HOUSING_AUTHORITY = "housing_authority"


@dataclass
class Step:
    key: str
    label: str
    done: bool
    detail: str
    href: str
    unlocks: str
    missing: list[str] = field(default_factory=list)
    optional_hints: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _count(db: Session, model, property_id: int) -> int:
    return db.query(func.count(model.id)).filter(model.property_id == property_id).scalar() or 0


def _identity(prop: Property) -> Step:
    missing = []
    if not (prop.city and prop.state):
        missing.append("city and state (this places the property in a market)")
    if not (prop.website_url or prop.domain):
        missing.append("website (owned-domain matching for citations)")
    hints = []
    if not (prop.aliases or []):
        hints.append("Add aliases AI might use for the name (for example without \"Apartments\").")
    done = not missing
    detail = (
        f"{prop.name}, {prop.city}, {prop.state}; site {prop.domain or prop.website_url}" if done
        else "Beacon needs a market and a website to score this property."
    )
    return Step("identity", "Identity", done, detail, f"/properties?property_id={prop.id}",
                "Market assignment, owned-domain citation matching, prompt generation", missing, hints)


def _data(db: Session, prop: Property) -> Step:
    pid = prop.id
    feeds = []
    ga4 = _count(db, GA4SessionsDaily, pid)
    gsc = _count(db, GSCPerformanceDaily, pid)
    if ga4:
        feeds.append(f"GA4 ({ga4} days)")
    if gsc:
        feeds.append(f"Search Console ({gsc} rows)")
    gbp = _count(db, GBPMetricsDaily, pid)
    if gbp:
        feeds.append("Business Profile")
    reviews = _count(db, PropertyReview, pid)
    if reviews:
        feeds.append(f"{reviews} reviews")
    leads = _count(db, CRMLead, pid)
    if leads:
        feeds.append(f"{leads} CRM leads")
    connected = (
        db.query(func.count(DataConnection.id))
        .filter(DataConnection.property_id == pid, DataConnection.oauth_status == OAuthStatus.CONNECTED)
        .scalar() or 0
    )
    done = bool(ga4 or gsc)
    missing = []
    if not ga4:
        missing.append("GA4 traffic (connect Google or upload the export)")
    if not gsc:
        missing.append("Search Console (connect Google or upload the Dates export)")
    hints = []
    if not reviews:
        hints.append("Reviews unlock Review IQ and the sentiment side of Semantic Intelligence.")
    if not leads:
        hints.append("CRM leads let the Executive report tie AI referrals to inquiries.")
    detail = ("; ".join(feeds) + (f"; {connected} Google connection(s)" if connected else "")) if feeds else (
        "No first-party data yet. Google auto-sync is the easiest path." if not connected
        else f"{connected} Google connection(s) linked, first sync pending.")
    return Step("data", "Data", done, detail, f"/uploads?property_id={pid}",
                "SEO, Executive, Audience and Content Impact reports; AI referral sessions", missing, hints)


def _facts(db: Session, prop: Property) -> Step:
    pid = prop.id
    profile = db.query(PropertyProfile).filter_by(property_id=pid).one_or_none()
    attrs = prop.attributes or {}
    recorded = [k for k in ("pet_policy", "rent_range", "amenities", "floor_plans") if attrs.get(k)]
    pages = _count(db, PropertyContent, pid)
    missing = []
    if profile is None:
        missing.append("Property Context (regulatory status and marketing restrictions gate every recommendation)")
    hints = []
    if profile is not None and not profile.property_type and prop.property_type != HOUSING_AUTHORITY:
        hints.append("Set the property type on Property Context (conventional, luxury, student, senior, affordable) "
                     "so the prompt library asks what that audience asks.")
    if prop.property_type == HOUSING_AUTHORITY:
        hints.append("Housing authorities hold different policies per development; per-development facts are not "
                     "recorded yet, so AI claims about policies are shown, never marked wrong.")
    elif not recorded:
        hints.append("Record pets, rent range and amenities so AI claims about them can be checked.")
    if not pages:
        hints.append("Add the property's own pages so content gaps compare against what the site already says.")
    done = profile is not None
    parts = []
    if profile is not None:
        parts.append("Property Context set" + (f" ({profile.property_type})" if profile.property_type else ""))
    if recorded:
        parts.append("facts: " + ", ".join(r.replace("_", " ") for r in recorded))
    if pages:
        parts.append(f"{pages} site pages")
    detail = "; ".join(parts) if parts else "Nothing recorded. Recommendations stay withheld until Context is set."
    return Step("facts", "Facts", done, detail, f"/property-context?property_id={pid}",
                "Recommendations, claim verification on the Accuracy tab, content gaps", missing, hints)


def _competitors(db: Session, prop: Property) -> Step:
    n = _count(db, Competitor, prop.id)
    done = n >= 1
    missing = [] if done else ["At least one tracked competitor (confirm the ones AI already names on the Competitors tab)"]
    hints = ["Two or three is typical; only tracked competitors count in Share of Voice."] if 0 < n < 2 else []
    detail = f"{n} tracked competitor(s)" if done else "None tracked. Share of Voice has no denominator yet."
    return Step("competitors", "Competitors", done, detail, f"/competitors?property_id={prop.id}",
                "Share of Voice, Competitor Win Rate, rankings by topic", missing, hints)


def _prompts(db: Session, prop: Property) -> Step:
    pid = prop.id
    assigned = len(assignments_for_property(db, pid))
    standing = db.query(func.count(AIVisibilityPrompt.id)).filter(AIVisibilityPrompt.property_id == pid).scalar() or 0
    done = assigned > 0 or standing > 0
    parts = []
    if assigned:
        parts.append(f"{assigned} prompt cluster(s) assigned")
    if standing:
        parts.append(f"{standing} standing prompt(s)")
    missing = [] if done else ["Generate the prompt library (one click on the Prompts tab)"]
    detail = "; ".join(parts) if parts else "No prompts yet. Generation uses identity, facts and the market."
    return Step("prompts", "Prompts", done, detail, f"/ai-visibility/prompts?property_id={pid}",
                "Monitoring runs; every AI Visibility metric", missing)


def _monitoring(db: Session, prop: Property) -> Step:
    pid = prop.id
    eligible = (
        db.query(func.count(AIPropertyObservation.id))
        .filter(AIPropertyObservation.property_id == pid, AIPropertyObservation.eligible.is_(True))
        .scalar() or 0
    )
    done = eligible > 0
    missing = [] if done else ["Run a few prompts (or wait for the scheduled cycle) to get the first monitored answers"]
    detail = f"{eligible} monitored answer(s) scored" if done else "No monitored answers yet."
    return Step("monitoring", "Monitoring", done, detail, f"/ai-visibility?property_id={pid}",
                "AI Visibility Overview, citations, sources, accuracy, trends", missing)


def property_setup(db: Session, property_id: int) -> dict:
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    steps = [
        _identity(prop),
        _data(db, prop),
        _facts(db, prop),
        _competitors(db, prop),
        _prompts(db, prop),
        _monitoring(db, prop),
    ]
    done = sum(1 for s in steps if s.done)
    next_step = next((s for s in steps if not s.done), None)
    return {
        "property_id": property_id,
        "property_name": prop.name,
        "property_type": prop.property_type,
        "is_sample": bool((prop.attributes or {}).get("sample_data")),
        "steps": [s.as_dict() for s in steps],
        "done": done,
        "total": len(steps),
        "percent": round(100 * done / len(steps)),
        "complete": done == len(steps),
        "next": next_step.as_dict() if next_step else None,
    }
