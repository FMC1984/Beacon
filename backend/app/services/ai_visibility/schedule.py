"""Standing-prompt scheduling for AI Visibility.

run_standing_prompts() executes every active prompt for a property (respecting
the per-property daily budget), then snapshots the resulting visibility score
into history. Runs weekly via the app's background loop, or on demand from the
UI. The score point is honest: below the sample-size gate it stores None with
the current sample size, not a fabricated number.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import (
    AIVisibilityPrompt,
    AIVisibilityScoreHistory,
    Property,
)
from app.services.ai_visibility.analyzer import analyze_ai_visibility
from app.services.ai_visibility.execution import RateLimitExceeded, run_query
from app.services.ai_visibility.providers import get_ai_visibility_provider

logger = logging.getLogger("beacon.ai_visibility.schedule")

_SUGGESTIONS = (
    Path(__file__).resolve().parent.parent.parent
    / "reference_data"
    / "ai_visibility_prompt_suggestions.json"
)


def prompt_suggestions(prop: Property) -> list[str]:
    """Type-appropriate starter prompts with the property's own name/city/state
    filled in. Placeholders with no value are dropped from that suggestion."""
    cfg = json.loads(_SUGGESTIONS.read_text())
    ptype = getattr(prop, "property_type", None) or "multifamily_apartment"
    raw = cfg["by_type"].get(ptype, cfg["by_type"]["multifamily_apartment"])
    fills = {
        "name": prop.name or "",
        "city": prop.city or "",
        "state": prop.state or "",
        "county": (prop.city or "").replace(" ", " ") or "",
    }
    out = []
    for template in raw:
        needed = [k for k in fills if "{" + k + "}" in template]
        if any(not fills[k] for k in needed):
            continue  # do not emit a half-filled prompt
        out.append(template.format(**fills))
    return out


def run_standing_prompts(
    db: Session, property_id: int, provider=None, now: datetime | None = None
) -> dict:
    """Execute active prompts for one property, then snapshot the score.
    Stops early (honestly) if the daily budget is hit; whatever ran still
    counts toward the snapshot."""
    now = now or datetime.now(timezone.utc)
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    provider = provider or get_ai_visibility_provider()

    prompts = (
        db.query(AIVisibilityPrompt)
        .filter(
            AIVisibilityPrompt.property_id == property_id,
            AIVisibilityPrompt.active.is_(True),
        )
        .order_by(AIVisibilityPrompt.id)
        .all()
    )

    ran, budget_hit, errors = 0, False, []
    for p in prompts:
        try:
            run_query(db, property_id, p.prompt_text, p.platform, provider=provider, now=now)
            p.last_run_at = now
            db.commit()
            ran += 1
        except RateLimitExceeded:
            budget_hit = True
            break
        except Exception as exc:  # one bad prompt never aborts the batch
            errors.append(str(exc)[:200])
            logger.warning("standing prompt failed: property=%s err=%s", property_id, exc)

    snapshot = snapshot_score(db, property_id, now=now)
    return {
        "prompts_run": ran,
        "budget_hit": budget_hit,
        "errors": errors,
        "score": snapshot["score"],
        "sample_size": snapshot["sample_size"],
    }


# Monthly prompts with runs_per_cycle=2 run on these days of the month; a
# single-run monthly uses just the first. Deterministic spread, no jitter.
MONTHLY_RUN_DAYS = [1, 15]
# A weekly prompt is due again after this many days (slightly under 7 so a
# daily scheduler tick never skips a week due to timing).
WEEKLY_DUE_DAYS = 6.5


def _is_due(p, now: datetime) -> bool:
    # SQLite hands datetimes back naive; treat stored values as UTC.
    last = p.last_run_at
    if last is not None and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if p.cadence == "monthly":
        run_days = MONTHLY_RUN_DAYS[: max(1, min(p.runs_per_cycle, len(MONTHLY_RUN_DAYS)))]
        if now.day not in run_days:
            return False
        # Not already run today (the daily tick must be idempotent).
        return last is None or last.date() < now.date()
    # weekly (default)
    if last is None:
        return True
    return (now - last).total_seconds() >= WEEKLY_DUE_DAYS * 86400


def run_due_prompts(
    db: Session, property_id: int, provider=None, now: datetime | None = None
) -> dict:
    """Cadence-aware runner for the daily scheduler tick: weeklies run every
    ~7 days, monthlies on the 1st and 15th (runs_per_cycle=2) or the 1st only
    (=1). Idempotent within a day; the daily budget still caps spend. Returns
    the same summary shape as run_standing_prompts plus what was due."""
    now = now or datetime.now(timezone.utc)
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")

    prompts = (
        db.query(AIVisibilityPrompt)
        .filter(
            AIVisibilityPrompt.property_id == property_id,
            AIVisibilityPrompt.active.is_(True),
        )
        .order_by(AIVisibilityPrompt.id)
        .all()
    )
    due = [p for p in prompts if _is_due(p, now)]
    if not due:
        return {"prompts_due": 0, "prompts_run": 0, "budget_hit": False, "errors": []}

    provider = provider or get_ai_visibility_provider()
    ran, budget_hit, errors = 0, False, []
    for p in due:
        try:
            run_query(db, property_id, p.prompt_text, p.platform, provider=provider, now=now)
            p.last_run_at = now
            db.commit()
            ran += 1
        except RateLimitExceeded:
            budget_hit = True
            break
        except Exception as exc:  # one bad prompt never aborts the batch
            errors.append(str(exc)[:200])
            logger.warning("due prompt failed: property=%s err=%s", property_id, exc)

    snapshot = snapshot_score(db, property_id, now=now)
    return {
        "prompts_due": len(due),
        "prompts_run": ran,
        "budget_hit": budget_hit,
        "errors": errors,
        "score": snapshot["score"],
        "sample_size": snapshot["sample_size"],
    }


def snapshot_score(db: Session, property_id: int, now: datetime | None = None) -> dict:
    """Compute the current visibility analysis and append a history point."""
    now = now or datetime.now(timezone.utc)
    analysis = analyze_ai_visibility(db, property_id)
    score_obj = analysis.get("score")
    score = score_obj["value"] if score_obj else None
    sample = (analysis.get("sample") or {}).get("total_queries", 0)
    rate = (analysis.get("mention") or {}).get("rate")
    row = AIVisibilityScoreHistory(
        property_id=property_id,
        captured_at=now,
        score=score,
        sample_size=sample,
        mention_rate=rate,
    )
    db.add(row)
    db.commit()
    return {"score": score, "sample_size": sample, "mention_rate": rate}


def score_history(db: Session, property_id: int) -> list[dict]:
    rows = (
        db.query(AIVisibilityScoreHistory)
        .filter(AIVisibilityScoreHistory.property_id == property_id)
        .order_by(AIVisibilityScoreHistory.captured_at)
        .all()
    )
    return [
        {
            "captured_at": r.captured_at.isoformat(),
            "score": r.score,
            "sample_size": r.sample_size,
            "mention_rate": r.mention_rate,
        }
        for r in rows
    ]
