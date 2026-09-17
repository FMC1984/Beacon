"""Cross-property benchmarks (flow P3).

A property's Observatory metrics beside the average of the OTHER monitored
properties Beacon holds, so a leasing team can tell "40% AI Visibility" from
"40% when comparable communities average 55%". Two pools: every other
property, and the ones with the same Property Context type (segment).

Rules that keep this honest:
  * a pool needs MIN_POOL properties, each with enough monitored answers in
    the window, or the benchmark is UNAVAILABLE with the reason;
  * sample (demo) properties are benchmarked only against sample
    properties, and real ones only against real ones, never mixed;
  * the property itself is never in its own pool;
  * pool members are never named: the number is an average, the property
    count and organization count are the only things disclosed.
"""

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models import Property
from app.models.property_profile import PropertyProfile
from app.services.observatory import LABEL_MEASURED, LABEL_UNAVAILABLE, utc_today
from app.services.observatory.metrics import metrics_for_window
from app.services.observatory.tenancy import property_org_id
from app.services.reporting import pct_point_change

MIN_POOL = 3
METRICS = ("ai_visibility", "citation_rate", "share_of_voice", "recommendation_rate")


def _is_sample(p: Property) -> bool:
    return bool((p.attributes or {}).get("sample_data"))


def _segment(db: Session, pid: int) -> str | None:
    prof = db.query(PropertyProfile).filter_by(property_id=pid).one_or_none()
    return (prof.property_type or None) if prof else None


def _pool_metrics(db: Session, members: list[Property], start: date, end: date) -> dict:
    """Per metric: average over members whose metric cleared the sample gate."""
    vals: dict[str, list[float]] = {k: [] for k in METRICS}
    orgs: set[int | None] = set()
    counted: set[int] = set()
    for p in members:
        m = metrics_for_window(db, p.id, start, end)
        for k in METRICS:
            v = m[k]["value"]
            if v is not None:
                vals[k].append(v)
                counted.add(p.id)
                orgs.add(property_org_id(db, p.id))
    out = {}
    for k in METRICS:
        n = len(vals[k])
        if n < MIN_POOL:
            out[k] = {"value": None, "properties": n, "data_label": LABEL_UNAVAILABLE,
                      "note": f"Needs at least {MIN_POOL} other properties with enough monitored answers ({n} so far)."}
        else:
            out[k] = {"value": round(sum(vals[k]) / n, 4), "properties": n, "data_label": LABEL_MEASURED}
    return {"metrics": out, "properties": len(counted), "organizations": len(orgs)}


def property_benchmark(db: Session, property_id: int, days: int = 30, today: date | None = None) -> dict:
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    today = today or utc_today()
    start, end = today - timedelta(days=days - 1), today
    own = metrics_for_window(db, property_id, start, end)
    sample = _is_sample(prop)
    segment = _segment(db, property_id)

    others = [
        p for p in db.query(Property).filter(Property.is_active.is_(True), Property.id != property_id).all()
        if _is_sample(p) == sample
    ]
    same_segment = [p for p in others if segment and _segment(db, p.id) == segment]
    all_pool = _pool_metrics(db, others, start, end)
    seg_pool = _pool_metrics(db, same_segment, start, end) if segment else None

    def compare(pool: dict | None) -> dict:
        rows = {}
        for k in METRICS:
            mine = own[k]["value"]
            bench = pool["metrics"][k] if pool else {"value": None, "properties": 0, "data_label": LABEL_UNAVAILABLE,
                                                     "note": "Set the property type on Property Context to compare with the same kind of community."}
            rows[k] = {
                "property_value": mine,
                "benchmark_value": bench["value"],
                "properties": bench["properties"],
                "data_label": bench["data_label"],
                "note": bench.get("note"),
                "point_change": pct_point_change(mine, bench["value"]) if mine is not None and bench["value"] is not None else None,
            }
        return rows

    return {
        "property_id": property_id,
        "window": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "is_sample": sample,
        "segment": segment,
        "minimum_pool": MIN_POOL,
        "all": {"pool": {"properties": all_pool["properties"], "organizations": all_pool["organizations"]},
                "metrics": compare(all_pool)},
        "segment_pool": ({"pool": {"properties": seg_pool["properties"], "organizations": seg_pool["organizations"]},
                          "metrics": compare(seg_pool)} if seg_pool else {"pool": {"properties": 0, "organizations": 0},
                                                                          "metrics": compare(None)}),
        "note": ("Benchmarks average the other monitored properties Beacon holds (sample communities only against "
                 "sample ones), counting only properties with enough answers in the window. Members are never named."),
    }
