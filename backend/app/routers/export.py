"""Data export endpoint. Returns a ZIP of CSVs for one property or the whole
portfolio - see app/services/export.py for what goes in the bundle."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.export import build_export

router = APIRouter(prefix="/export", tags=["export"])


@router.get("")
def export_data(
    property_id: int | None = Query(default=None),
    company_id: int | None = Query(default=None),
    unassigned: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    try:
        data, filename = build_export(db, property_id, company_id, unassigned)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
