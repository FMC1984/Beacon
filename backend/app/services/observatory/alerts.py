"""Observatory alerts (Phase 19, slice 5).

Rules over the daily rollups (SQL only, no model calls), thresholds in
reference_data/ai_alert_thresholds.json:

  visibility_drop      AI Visibility fell by >= N points week over week
  citation_lost        the owned site was cited last window and not at all now
  competitor_surge     Competitor Win Rate rose by >= N points
  claim_conflict       an AI answer contradicts a fact Beacon holds

Both windows must meet the minimum response sample. Alerts are deduplicated
by a key that includes the window end, so re-running detection the same day
never duplicates; wording states what changed, never why.
"""

import json
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import AIClaim, AIVisibilityAlert, Property
from app.models.ai_intelligence import ALERT_OPEN, CLAIM_CONFLICT
from app.services.observatory import LABEL_MEASURED, LABEL_OBSERVED, utc_today
from app.services.observatory.metrics import metrics_for_window
from app.services.observatory.tenancy import property_org_id
from app.services.jobs.queue import utcnow

_REFERENCE = Path(__file__).resolve().parent.parent.parent / "reference_data" / "ai_alert_thresholds.json"


@lru_cache(maxsize=1)
def thresholds() -> dict:
    return json.loads(_REFERENCE.read_text())


def _upsert(db: Session, key: str, **fields) -> tuple[AIVisibilityAlert, bool]:
    row = db.query(AIVisibilityAlert).filter_by(dedupe_key=key).one_or_none()
    if row is not None:
        return row, False
    row = AIVisibilityAlert(dedupe_key=key, status=ALERT_OPEN, **fields)
    db.add(row)
    db.flush()
    return row, True


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{round(v * 100)}%"


def detect_property_alerts(db: Session, property_id: int, today: date | None = None) -> list[AIVisibilityAlert]:
    cfg = thresholds()
    today = today or utc_today()
    days = int(cfg["window_days"])
    cur_start, cur_end = today - timedelta(days=days - 1), today
    prev_end = cur_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    cur = metrics_for_window(db, property_id, cur_start, cur_end)
    prev = metrics_for_window(db, property_id, prev_start, prev_end)
    min_n = int(cfg["min_responses_per_window"])
    org_id = property_org_id(db, property_id)
    prop = db.get(Property, property_id)
    market_id = prop.market_id if prop else None
    created: list[AIVisibilityAlert] = []
    window = {"current": [cur_start.isoformat(), cur_end.isoformat()],
              "previous": [prev_start.isoformat(), prev_end.isoformat()]}
    base = dict(organization_id=org_id, property_id=property_id, market_id=market_id)

    sample_ok = cur["counts"]["eligible_count"] >= min_n and prev["counts"]["eligible_count"] >= min_n
    if sample_ok:
        a, b = prev["ai_visibility"]["value"], cur["ai_visibility"]["value"]
        if a is not None and b is not None and a - b >= cfg["visibility_drop_points"]:
            row, new = _upsert(
                db, f"visibility_drop:{property_id}:{cur_end.isoformat()}", **base,
                alert_type="visibility_drop", severity="high",
                title=f"AI Visibility fell {round((a - b) * 100)} pts week over week",
                detail=(f"Mentioned in {cur['ai_visibility']['numerator']} of {cur['ai_visibility']['denominator']} "
                        f"monitored answers ({_pct(b)}), down from {prev['ai_visibility']['numerator']} of "
                        f"{prev['ai_visibility']['denominator']} ({_pct(a)}). This describes a change in monitored "
                        "answers, not its cause."),
                evidence={"window": window}, metric_before=a, metric_after=b, data_label=LABEL_MEASURED,
            )
            if new:
                created.append(row)

        prev_cited = prev["citation_rate"]["numerator"]
        if prev_cited >= cfg["citation_lost_min_previous_cited"] and cur["citation_rate"]["numerator"] == 0:
            row, new = _upsert(
                db, f"citation_lost:{property_id}:{cur_end.isoformat()}", **base,
                alert_type="citation_lost", severity="medium",
                title="The property's own site stopped being cited",
                detail=(f"Cited in {prev_cited} monitored answers last window and in none of "
                        f"{cur['counts']['eligible_count']} this window."),
                evidence={"window": window}, metric_before=prev["citation_rate"]["value"],
                metric_after=cur["citation_rate"]["value"], data_label=LABEL_MEASURED,
            )
            if new:
                created.append(row)

        a, b = prev["competitor_win_rate"]["value"], cur["competitor_win_rate"]["value"]
        if a is not None and b is not None and b - a >= cfg["competitor_win_rise_points"]:
            row, new = _upsert(
                db, f"competitor_surge:{property_id}:{cur_end.isoformat()}", **base,
                alert_type="competitor_surge", severity="medium",
                title=f"Tracked competitors won {round((b - a) * 100)} pts more answers",
                detail=(f"A tracked competitor appeared without the property in {_pct(b)} of monitored answers, "
                        f"up from {_pct(a)}."),
                evidence={"window": window}, metric_before=a, metric_after=b, data_label=LABEL_MEASURED,
            )
            if new:
                created.append(row)

    for claim in db.query(AIClaim).filter_by(property_id=property_id, verification_status=CLAIM_CONFLICT, status="open").all():
        row, new = _upsert(
            db, f"claim_conflict:{property_id}:{claim.id}", **base,
            alert_type="claim_conflict", severity=claim.severity or "medium",
            title=f"AI answer contradicts a recorded fact ({claim.claim_type.replace('_', ' ')})",
            detail=f"\"{claim.claim_value}\": {claim.evidence}",
            evidence={"claim_id": claim.id, "response_ids": claim.response_ids or []}, data_label=LABEL_OBSERVED,
        )
        if new:
            created.append(row)
    db.commit()
    return created


def escalate(db: Session, alert: AIVisibilityAlert, now: datetime | None = None) -> int:
    """Put the property's scheduled prompts on the watchlist tier for a while."""
    from app.models import AIRunSchedule

    if alert.property_id is None or alert.severity != "high":
        return 0
    now = now or utcnow()
    until = now + timedelta(days=int(thresholds()["escalation_days"]))
    rows = db.query(AIRunSchedule).filter(
        (AIRunSchedule.property_id == alert.property_id)
        | ((AIRunSchedule.market_id == alert.market_id) & AIRunSchedule.property_id.is_(None))
    ).all() if alert.market_id else db.query(AIRunSchedule).filter_by(property_id=alert.property_id).all()
    for r in rows:
        r.tier_override = "watchlist"
        r.escalation_until = until
        r.next_run_at = min(r.next_run_at or now, now)
    alert.escalated = bool(rows)
    db.commit()
    return len(rows)


def alert_out(a: AIVisibilityAlert) -> dict:
    return {
        "id": a.id, "property_id": a.property_id, "market_id": a.market_id, "alert_type": a.alert_type,
        "severity": a.severity, "title": a.title, "detail": a.detail, "evidence": a.evidence,
        "metric_before": a.metric_before, "metric_after": a.metric_after, "data_label": a.data_label,
        "status": a.status, "escalated": a.escalated,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }
