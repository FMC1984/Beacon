from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Company, Property
from app.services.metrics import build_dashboard

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
def dashboard(
    property_id: int | None = Query(default=None),
    company_id: int | None = Query(default=None),
    unassigned: bool = Query(default=False),
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    if property_id is not None and db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    if company_id is not None and db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="Company not found.")
    return build_dashboard(
        db, property_id, days, company_id=company_id, unassigned=unassigned
    )
