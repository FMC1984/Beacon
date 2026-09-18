"""Per-platform breakdown (roadmap item 1: platform-ready structure).

One row per AI platform on the roster, live or not: the Observatory metrics
from that platform's own rollups and the sources that platform cites most.
A platform that is not producing answers says why (needs a key, connector
planned, vendor has no API) instead of showing zeros, so the screen is
complete today with one platform and fills in as keys are added, with no
code change.
"""

from collections import Counter
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import AICitation, AIPropertyObservation, Property
from app.services.ai_visibility.reference import platform_availability, platforms
from app.services.observatory import LABEL_MEASURED, utc_today
from app.services.observatory.metrics import _window, metrics_for_window

TOP_SOURCES = 3


def platform_breakdown(db: Session, property_id: int, days: int = 30, today: date | None = None) -> dict:
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    is_sample_property = bool((prop.attributes or {}).get("sample_data"))
    today = today or utc_today()
    start, end = _window(days, today)
    lo = datetime.combine(start, datetime.min.time())
    hi = datetime.combine(end + timedelta(days=1), datetime.min.time())

    # Citations per platform for this property's scored answers.
    pairs = (
        db.query(AIPropertyObservation.platform, AICitation.domain)
        .join(AICitation, AICitation.response_id == AIPropertyObservation.response_id)
        .filter(AIPropertyObservation.property_id == property_id, AIPropertyObservation.eligible.is_(True),
                AIPropertyObservation.observed_at >= lo, AIPropertyObservation.observed_at < hi)
        .all()
    )
    by_platform: dict[str, Counter] = {}
    for platform, domain in pairs:
        by_platform.setdefault(platform, Counter())[domain] += 1

    rows = []
    for p in platforms():
        key = p["key"]
        m = metrics_for_window(db, property_id, start, end, platform=key)
        cites = by_platform.get(key, Counter())
        total = sum(cites.values())
        availability = platform_availability(key)
        answers = m["counts"]["eligible_count"]
        is_sample_demo = is_sample_property and availability["state"] != "live" and answers > 0
        rows.append({
            "platform": key, "label": p["label"],
            "availability": availability,
            "is_sample_demo": is_sample_demo,
            "answers": answers,
            "ai_visibility": m["ai_visibility"], "citation_rate": m["citation_rate"],
            "share_of_voice": m["share_of_voice"], "recommendation_rate": m["recommendation_rate"],
            "top_sources": [{"domain": d, "citations": n, "share": round(n / total, 4)} for d, n in cites.most_common(TOP_SOURCES)],
            "total_citations": total,
        })
    rows.sort(key=lambda r: (r["availability"]["state"] != "live", -r["answers"], r["label"]))
    return {
        "property_id": property_id, "data_label": LABEL_MEASURED,
        "window": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "platforms": rows,
        "live": sum(1 for r in rows if r["availability"]["state"] == "live"),
        "note": ("Each platform is measured from its own answers. A platform that is not connected shows why and "
                 "contributes nothing to any number; Beacon never estimates a platform it did not query. Rows "
                 "flagged is_sample_demo are scripted sample answers on the Sample Portfolio, shown so this screen "
                 "is legible before a key is added; they are never real provider traffic."),
    }
