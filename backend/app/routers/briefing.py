"""Monthly Strategic Briefing API (Phase 17A).

- GET /api/briefing            live-composed briefing for a property + month
  (defaults to the latest month with data).
- POST /api/briefing/generate freezes the current composition as a snapshot
  (upsert per property + month) so it powers Reports History and never changes
  on later re-sync.
- GET /api/briefing/history    list frozen snapshots for a property.
- GET /api/briefing/{id}       fetch one frozen snapshot verbatim.
"""

import secrets
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import MonthlyBriefing, Property
from app.services.reporting_briefing import _latest_data_month, compose_briefing

router = APIRouter(prefix="/briefing", tags=["briefing"])


def _resolve_month(db, property_id, year, month, today):
    if year and month:
        if not (1 <= month <= 12):
            raise HTTPException(status_code=422, detail="Month must be 1-12.")
        return year, month
    return _latest_data_month(db, property_id, today)


@router.get("")
def get_briefing(
    property_id: int | None = Query(default=None),
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if property_id is None:
        return {
            "scope_required": True,
            "message": "Select a single property to view its Monthly Strategic Briefing.",
        }
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    today = date.today()
    y, m = _resolve_month(db, property_id, year, month, today)
    return {"scope_required": False, **compose_briefing(db, property_id, y, m, today=today)}


@router.post("/generate")
def generate_briefing(
    property_id: int = Query(...),
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    today = date.today()
    y, m = _resolve_month(db, property_id, year, month, today)
    payload = compose_briefing(db, property_id, y, m, today=today)
    start = date.fromisoformat(payload["period"]["start"])
    end = date.fromisoformat(payload["period"]["end"])

    # Upsert: one frozen snapshot per property + month; regenerating replaces it.
    existing = (
        db.query(MonthlyBriefing)
        .filter(
            MonthlyBriefing.property_id == property_id,
            MonthlyBriefing.period_start == start,
        )
        .first()
    )
    if existing:
        existing.payload = payload
        existing.period_end = end
        existing.generated_at = datetime.now(timezone.utc)
        row = existing
    else:
        row = MonthlyBriefing(
            property_id=property_id, period_start=start, period_end=end, payload=payload
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "status": "generated",
        "id": row.id,
        "period": payload["period"],
        "generated_at": row.generated_at.isoformat(),
    }


@router.get("/history")
def briefing_history(
    property_id: int = Query(...),
    db: Session = Depends(get_db),
):
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    rows = (
        db.query(MonthlyBriefing)
        .filter(MonthlyBriefing.property_id == property_id)
        .order_by(MonthlyBriefing.period_start.desc())
        .all()
    )
    return {
        "property_id": property_id,
        "snapshots": [
            {
                "id": r.id,
                "period_label": r.payload.get("period", {}).get("label"),
                "period_start": r.period_start.isoformat(),
                "period_end": r.period_end.isoformat(),
                "generated_at": r.generated_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.post("/strategist")
def strategist(
    property_id: int = Query(...),
    year: int | None = Query(default=None),
    month: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Manual (button-triggered - it can spend OpenAI budget): the grounded
    'If I Were Your Strategist' synthesis for the property's briefing month.
    Below the minimum grounded signal, a fixed template returns and the LLM is
    never called."""
    from app.services.strategist import build_strategist

    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    today = date.today()
    y, m = _resolve_month(db, property_id, year, month, today)
    briefing = compose_briefing(db, property_id, y, m, today=today)
    return build_strategist(briefing)


# NB: declared BEFORE /{briefing_id} - path ordering matters (see the
# ai_visibility router note in HANDOFF.md).
@router.get("/shared/{token}")
def get_shared_snapshot(token: str, db: Session = Depends(get_db)):
    """PUBLIC route (exempt from the access-key middleware): the frozen
    snapshot behind an unguessable share token. Snapshots are client-safe by
    construction (composed report data only, no internal RAG metadata); the
    token is the entire authorization, and revoking the share nulls it."""
    if not token or len(token) < 16:
        raise HTTPException(status_code=404, detail="Not found.")
    row = (
        db.query(MonthlyBriefing)
        .filter(MonthlyBriefing.share_token == token)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Not found.")
    return {
        "scope_required": False,
        "frozen": True,
        "shared": True,
        "generated_at": row.generated_at.isoformat(),
        **row.payload,
    }


@router.post("/{briefing_id}/share")
def share_snapshot(briefing_id: int, db: Session = Depends(get_db)):
    """Mint (or re-mint) the share token for a frozen snapshot. Re-sharing
    rotates the token, which invalidates any previously shared link."""
    row = db.get(MonthlyBriefing, briefing_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Briefing snapshot not found.")
    row.share_token = secrets.token_urlsafe(24)
    db.commit()
    return {
        "status": "shared",
        "id": row.id,
        "token": row.share_token,
        "path": f"/shared/briefing/{row.share_token}",
    }


@router.delete("/{briefing_id}/share")
def revoke_share(briefing_id: int, db: Session = Depends(get_db)):
    row = db.get(MonthlyBriefing, briefing_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Briefing snapshot not found.")
    row.share_token = None
    db.commit()
    return {"status": "revoked", "id": row.id}


@router.get("/{briefing_id}")
def get_snapshot(briefing_id: int, db: Session = Depends(get_db)):
    row = db.get(MonthlyBriefing, briefing_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Briefing snapshot not found.")
    return {
        "scope_required": False,
        "snapshot_id": row.id,
        "frozen": True,
        "generated_at": row.generated_at.isoformat(),
        **row.payload,
    }
