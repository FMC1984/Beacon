from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.deps import Principal, assert_property_access, current_principal
from app.db import get_db
from app.models import Company
from app.services.metrics import build_dashboard
from app.services.observatory.tenancy import company_org_id

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard")
def dashboard(
    property_id: int | None = Query(default=None),
    company_id: int | None = Query(default=None),
    unassigned: bool = Query(default=False),
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    if property_id is not None:
        assert_property_access(db, principal, property_id)
    if company_id is not None:
        if db.get(Company, company_id) is None:
            raise HTTPException(status_code=404, detail="Company not found.")
        if principal.org_id is not None and company_org_id(db, company_id) != principal.org_id:
            raise HTTPException(status_code=404, detail="Company not found.")
    return build_dashboard(
        db, property_id, days, company_id=company_id, unassigned=unassigned
    )
