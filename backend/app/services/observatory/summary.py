"""What Nora reads about the Observatory (flow P1).

Two deterministic readers, both computed in code before any model call:

  observatory_summary_text   one labeled summary chunk per property for
                             the RAG index (the same numbers the AI
                             Visibility tab shows, from the same rollups),
                             or None when there is nothing real to say.
  explain_visibility_change  the single prompt cluster whose own AI
                             Visibility change covers at least half of the
                             aggregate change in the same direction, so Nora
                             can offer a Supported Diagnosis instead of
                             guessing why visibility moved. None means Nora
                             must stay at Observation.

Nothing here is inferred: every figure comes from derived observations,
their daily rollups, tracked competitors and stored claims, and every rate
travels with its sample and its OBSERVED / MEASURED / MODELED label.
"""

from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AIClaim, AIClusterVisibilityDaily, AIPromptCluster, AIVisibilityAlert, AIVisibilityPrompt, Property
from app.models.ai_intelligence import ALERT_OPEN, CLAIM_CONFLICT
from app.services.ai_visibility.reference import MIN_QUERIES_FOR_VISIBILITY
from app.services.observatory import utc_today
from app.services.observatory.citation_pages import NOT_MENTIONED, top_citation_pages
from app.services.observatory.metrics import _window, metrics_for_window, source_influence
from app.services.observatory.topic_rankings import topic_rankings
from app.services.reporting import compare_points, pct_point_change, previous_window

WINDOW_DAYS = 30
# Below this many points the aggregate did not meaningfully move, so there
# is nothing to diagnose (a 15-point swing in one question "explaining" a
# half-point aggregate wobble would be noise dressed up as a finding).
MIN_AGGREGATE_CHANGE = 0.03


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{round(v * 100)}%"


def _change(cur: float | None, prev: float | None) -> str:
    c = compare_points(cur, prev)
    pts = c.get("point_change") if isinstance(c, dict) else None
    if pts is None:
        return ""
    p = round(pts * 100)
    return f" ({'+' if p >= 0 else ''}{p} pts vs the previous period)"


def observatory_summary_text(db: Session, property_id: int, days: int = WINDOW_DAYS, today: date | None = None) -> str | None:
    prop = db.get(Property, property_id)
    if prop is None:
        return None
    today = today or utc_today()
    start, end = _window(days, today)
    prev_start, prev_end = previous_window(start, end)
    cur = metrics_for_window(db, property_id, start, end)
    if cur["counts"]["eligible_count"] < MIN_QUERIES_FOR_VISIBILITY:
        return None
    prev = metrics_for_window(db, property_id, prev_start, prev_end)
    n = cur["counts"]["eligible_count"]

    lines = [
        f"AI Visibility Observatory summary for {prop.name} ({start.isoformat()} to {end.isoformat()}), "
        f"from {n} monitored AI answers. Monitoring runs are Beacon's own tests, not consumer impressions, "
        "and Beacon never reports AI search volume.",
    ]
    for key, label, tag in (
        ("ai_visibility", "AI Visibility (answers that name the property)", "MEASURED"),
        ("citation_rate", "Citation Rate (answers that cite the property's own site)", "MEASURED"),
        ("recommendation_rate", "Recommendation Rate (answers that put it among the top picks, rule-based)", "MODELED"),
    ):
        m, pm = cur[key], prev[key]
        if m["value"] is None:
            continue
        lines.append(f"{label}: {_pct(m['value'])} ({m['numerator']} of {m['denominator']}){_change(m['value'], pm['value'])}. {tag}.")
    sov = cur["share_of_voice"]
    if sov["value"] is not None:
        lines.append(
            f"Share of Voice against tracked competitors: {_pct(sov['value'])} "
            f"({sov['numerator']} of {sov['denominator']} mentions){_change(sov['value'], prev['share_of_voice']['value'])}. MEASURED."
        )

    src = source_influence(db, property_id, start, end, limit=3)
    if src.get("domains"):
        top = ", ".join(f"{d['domain']} ({_pct(d['share'])}, {d.get('source_type') or 'other'})" for d in src["domains"][:3])
        lines.append(f"Sources AI answers cite most: {top}. OBSERVED.")

    pages = top_citation_pages(db, property_id, days=days, today=today, limit=10)
    silent = [p for p in pages["pages"] if p["mentioned_on_page"] == NOT_MENTIONED][:2]
    if silent:
        lines.append(
            "Cited pages that do not mention the property: "
            + "; ".join(f"{p['normalized_url']} (cited {p['citations']} times)" for p in silent)
            + ". MEASURED by fetching the page."
        )

    rk = topic_rankings(db, property_id, days=days, today=today)
    if rk["topics"]:
        s = rk["summary"]
        lines.append(f"Rankings by question: leading on {s['leading']} of {s['topics']} monitored questions; {s['needs_work']} need work.")
        for t in [t for t in rk["topics"] if t["needs_work"]][:3]:
            lead = f", led by {t['leader']}" if t["leader"] and t["leader"] != prop.name else ""
            rank = f"#{t['property_rank']}" if t["property_rank"] else "not named"
            lines.append(f"- \"{t['prompt']}\": {rank} of {len(t['ranked'])}{lead} ({t['answers']} answers).")

    conflicts = (
        db.query(AIClaim)
        .filter(AIClaim.property_id == property_id, AIClaim.status == "open", AIClaim.verification_status == CLAIM_CONFLICT)
        .order_by(AIClaim.last_seen.desc())
        .limit(3)
        .all()
    )
    if conflicts:
        lines.append(
            f"Open fact conflicts ({len(conflicts)} shown): "
            + "; ".join(f"AI said \"{c.claim_text.strip()[:120]}\" but the recorded fact is {c.known_value or 'different'}" for c in conflicts)
            + ". MEASURED against Property Context."
        )
    alerts = (
        db.query(AIVisibilityAlert)
        .filter(AIVisibilityAlert.property_id == property_id, AIVisibilityAlert.status == ALERT_OPEN)
        .order_by(AIVisibilityAlert.created_at.desc())
        .limit(2)
        .all()
    )
    if alerts:
        lines.append("Open alerts: " + "; ".join(f"{a.title} ({a.severity})" for a in alerts) + ".")
    return "\n".join(lines).replace("—", ", ")


def explain_visibility_change(db: Session, property_id: int, days: int = WINDOW_DAYS, today: date | None = None) -> dict | None:
    """Same posture as explain_sov_change: returns the one prompt cluster whose
    AI Visibility change is at least half the aggregate change, in the same
    direction, with both windows above the sample minimum; otherwise None."""
    today = today or utc_today()
    start, end = _window(days, today)
    prev_start, prev_end = previous_window(start, end)
    cur = metrics_for_window(db, property_id, start, end)["ai_visibility"]
    prev = metrics_for_window(db, property_id, prev_start, prev_end)["ai_visibility"]
    if cur["value"] is None or prev["value"] is None:
        return None
    aggregate = pct_point_change(cur["value"], prev["value"])
    if not aggregate or abs(aggregate) < MIN_AGGREGATE_CHANGE:
        return None

    def per_cluster(lo: date, hi: date) -> dict[int, tuple[int, int]]:
        rows = (
            db.query(AIClusterVisibilityDaily.cluster_id, func.sum(AIClusterVisibilityDaily.mentioned_count),
                     func.sum(AIClusterVisibilityDaily.eligible_count))
            .filter(AIClusterVisibilityDaily.property_id == property_id,
                    AIClusterVisibilityDaily.day >= lo, AIClusterVisibilityDaily.day <= hi)
            .group_by(AIClusterVisibilityDaily.cluster_id)
            .all()
        )
        return {cid: (int(m or 0), int(e or 0)) for cid, m, e in rows}

    now_by, then_by = per_cluster(start, end), per_cluster(prev_start, prev_end)
    best = None
    for cid, (m, e) in now_by.items():
        pm, pe = then_by.get(cid, (0, 0))
        if e < MIN_QUERIES_FOR_VISIBILITY or pe < MIN_QUERIES_FOR_VISIBILITY:
            continue
        change = pct_point_change(m / e, pm / pe)
        if change is None or (change > 0) != (aggregate > 0) or abs(change) < abs(aggregate) * 0.5:
            continue
        if best is None or abs(change) > abs(best["point_change"]):
            best = {"cluster_id": cid, "point_change": change}
    if best is None:
        return None
    cluster = db.get(AIPromptCluster, best["cluster_id"])
    rep = db.get(AIVisibilityPrompt, cluster.representative_prompt_id) if cluster and cluster.representative_prompt_id else None
    best["prompt"] = rep.prompt_text if rep else (cluster.label if cluster else f"cluster {best['cluster_id']}")
    return {**best, "aggregate_point_change": aggregate}
