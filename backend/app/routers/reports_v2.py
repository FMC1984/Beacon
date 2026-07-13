"""Reports section API (Phase 16A foundation).

Named reports_v2 because app/routers would collide conceptually with the
existing generated-report model (app/models/reports.py, ReportType). This
router serves the Reports navigation section: tab metadata and per-source
data status. Report content endpoints arrive with each report's own phase.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Company, Property
from app.services.reporting import source_status
from app.services.reporting_csv import build_executive_csv, build_seo_csv
from app.services.reporting_executive import build_executive_report
from app.services.reporting_seo import build_seo_report

router = APIRouter(prefix="/reports", tags=["reports"])

# Single source of truth for the Reports tabs. status "planned" renders an
# honest placeholder; flipped to "available" as each phase lands.
REPORT_TABS = [
    {
        "key": "executive",
        "label": "Executive",
        "status": "available",
        "planned_phase": "16C",
        "summary": "Cross-source summary with a deterministic, cited narrative and top actions.",
    },
    {
        "key": "seo",
        "label": "SEO Performance",
        "status": "available",
        "planned_phase": "16B",
        "summary": "Search Console and GA4 organic performance, trends, ranking distribution, gains and losses.",
    },
    {
        "key": "geo",
        "label": "GEO Visibility",
        "status": "planned",
        "planned_phase": "16D",
        "summary": "Tested AI answer visibility, prompt matrix, source landscape, competitor share of tested answers.",
    },
    {
        "key": "aeo",
        "label": "AEO Readiness",
        "status": "planned",
        "planned_phase": "16E",
        "summary": "Explainable answer-engine readiness with question coverage and citation readiness.",
    },
    {
        "key": "semantic",
        "label": "Semantic Intelligence",
        "status": "planned",
        "planned_phase": "deferred",
        "summary": "Topic coverage across sources. Deferred with Phase 15c until there is enough indexed data to cluster meaningfully.",
    },
    {
        "key": "content-impact",
        "label": "Content Impact",
        "status": "planned",
        "planned_phase": "16F",
        "summary": "Content change log with before-and-after windows. Observed changes are never claimed as caused.",
    },
]


@router.get("/meta")
def reports_meta():
    return {"tabs": REPORT_TABS}


@router.get("/seo")
def seo_report(
    property_id: int | None = Query(default=None),
    company_id: int | None = Query(default=None),
    unassigned: bool = Query(default=False),
    days: int = Query(default=30, ge=1, le=365),
    compare: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    if property_id is not None and db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    if company_id is not None and db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="Company not found.")
    return build_seo_report(
        db,
        property_id,
        days,
        want_compare=compare,
        company_id=company_id,
        unassigned=unassigned,
    )


@router.get("/executive")
def executive_report(
    property_id: int | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
    compare: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    if property_id is not None and db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    return build_executive_report(db, property_id, days, want_compare=compare)


def _csv_response(content: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/seo/export.csv")
def seo_report_csv(
    property_id: int | None = Query(default=None),
    company_id: int | None = Query(default=None),
    unassigned: bool = Query(default=False),
    days: int = Query(default=30, ge=1, le=365),
    compare: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    if property_id is not None and db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    content, filename = build_seo_csv(
        db, property_id, days, compare,
        company_id=company_id, unassigned=unassigned,
    )
    return _csv_response(content, filename)


@router.get("/executive/export.csv")
def executive_report_csv(
    property_id: int | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
    compare: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    if property_id is not None and db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    try:
        content, filename = build_executive_csv(db, property_id, days, compare)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _csv_response(content, filename)


@router.get("/status")
def reports_status(
    property_id: int | None = Query(default=None),
    company_id: int | None = Query(default=None),
    unassigned: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    if property_id is not None and db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    if company_id is not None and db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="Company not found.")
    return source_status(
        db, property_id, company_id=company_id, unassigned=unassigned
    )
