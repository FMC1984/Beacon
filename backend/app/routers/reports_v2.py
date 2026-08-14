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
from app.services.reporting_aeo import build_aeo_report
from app.services.reporting_audience import build_audience_report
from app.services.reporting_content_impact import build_content_impact_report
from app.services.reporting_csv import (
    build_aeo_csv,
    build_audience_csv,
    build_content_impact_csv,
    build_executive_csv,
    build_geo_csv,
    build_seo_csv,
    build_sov_csv,
)
from app.services.reporting_executive import build_executive_report
from app.services.reporting_geo import build_geo_report, matrix_cell_evidence
from app.services.reporting_seo import build_seo_report
from app.services.reporting_share_of_voice import (
    build_sov_report,
    competitive_ranking,
    sov_kpi_card,
    sov_prompt_drilldown,
    sov_response_evidence,
    sov_topic_drilldown,
    winners_losers,
)

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
        "key": "audience",
        "label": "Audience",
        "status": "available",
        "planned_phase": "16G",
        "summary": "Where visitors come from: sessions and users by city and region from GA4, with the AI-referral split.",
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
        "status": "available",
        "planned_phase": "16D",
        "summary": "Tested AI answer visibility, prompt matrix, source landscape, competitor share of tested answers.",
    },
    {
        "key": "aeo",
        "label": "AEO Readiness",
        "status": "available",
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
        "status": "available",
        "planned_phase": "16F",
        "summary": "Content change log with before-and-after windows. Observed changes are never claimed as caused.",
    },
    {
        "key": "share-of-voice",
        "label": "AI Share of Voice",
        "status": "available",
        "planned_phase": "18B",
        "summary": "Property mentions against operator-named competitors in tested AI answers, by platform and topic, with drilldown to the response evidence.",
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


@router.get("/geo")
def geo_report(
    property_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if property_id is not None and db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    return build_geo_report(db, property_id)


@router.get("/aeo")
def aeo_report(
    property_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if property_id is not None and db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    return build_aeo_report(db, property_id)


@router.get("/content-impact")
def content_impact_report(
    property_id: int | None = Query(default=None),
    window: int = Query(default=30),
    db: Session = Depends(get_db),
):
    if property_id is not None and db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    return build_content_impact_report(db, property_id, window=window)


@router.get("/audience")
def audience_report(
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
    return build_audience_report(
        db, property_id, days, company_id=company_id, unassigned=unassigned
    )


@router.get("/geo/evidence")
def geo_matrix_evidence(
    property_id: int = Query(...),
    query_id: int = Query(...),
    db: Session = Depends(get_db),
):
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    try:
        return matrix_cell_evidence(db, property_id, query_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


def _sov_filters(
    topic_id: int | None, platform: str | None, prompt_id: int | None,
    competitor_id: int | None, audience: str | None, location: str | None,
    intent: str | None, priority: str | None,
) -> dict:
    return dict(
        topic_id=topic_id, platform=platform, prompt_id=prompt_id,
        competitor_id=competitor_id, audience=audience, location=location,
        intent=intent, priority=priority,
    )


@router.get("/share-of-voice")
def share_of_voice_report(
    property_id: int | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
    compare: bool = Query(default=False),
    topic_id: int | None = Query(default=None),
    platform: str | None = Query(default=None),
    prompt_id: int | None = Query(default=None),
    competitor_id: int | None = Query(default=None),
    audience: str | None = Query(default=None),
    location: str | None = Query(default=None),
    intent: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if property_id is not None and db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    try:
        return build_sov_report(
            db, property_id, days, compare,
            **_sov_filters(topic_id, platform, prompt_id, competitor_id, audience, location, intent, priority),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/share-of-voice/kpi")
def share_of_voice_kpi(
    property_id: int = Query(...),
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    try:
        return sov_kpi_card(db, property_id, days)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/share-of-voice/ranking")
def share_of_voice_ranking(
    property_id: int = Query(...),
    days: int = Query(default=30, ge=1, le=365),
    topic_id: int | None = Query(default=None),
    platform: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    try:
        ranking = competitive_ranking(db, property_id, days, topic_id=topic_id, platform=platform)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ranking": ranking, "winners_losers": winners_losers(db, property_id, days)}


@router.get("/share-of-voice/topics/{topic_id}")
def share_of_voice_topic_drilldown(
    topic_id: int,
    property_id: int = Query(...),
    days: int = Query(default=30, ge=1, le=365),
    platform: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    try:
        return sov_topic_drilldown(db, property_id, topic_id, days, platform=platform)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/share-of-voice/prompts/{prompt_id}")
def share_of_voice_prompt_drilldown(
    prompt_id: int,
    property_id: int = Query(...),
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(get_db),
):
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    try:
        return sov_prompt_drilldown(db, property_id, prompt_id, days)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/share-of-voice/evidence")
def share_of_voice_evidence(
    property_id: int = Query(...),
    response_id: int = Query(...),
    db: Session = Depends(get_db),
):
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    try:
        return sov_response_evidence(db, property_id, response_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


def _csv_response(content: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/audience/export.csv")
def audience_report_csv(
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
    content, filename = build_audience_csv(
        db, property_id, days, company_id=company_id, unassigned=unassigned
    )
    return _csv_response(content, filename)


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


@router.get("/geo/export.csv")
def geo_report_csv(
    property_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if property_id is not None and db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    try:
        content, filename = build_geo_csv(db, property_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _csv_response(content, filename)


@router.get("/aeo/export.csv")
def aeo_report_csv(
    property_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if property_id is not None and db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    try:
        content, filename = build_aeo_csv(db, property_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _csv_response(content, filename)


@router.get("/content-impact/export.csv")
def content_impact_csv(
    property_id: int | None = Query(default=None),
    window: int = Query(default=30),
    db: Session = Depends(get_db),
):
    if property_id is not None and db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    try:
        content, filename = build_content_impact_csv(db, property_id, window=window)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _csv_response(content, filename)


@router.get("/share-of-voice/export.csv")
def share_of_voice_csv(
    property_id: int | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
    topic_id: int | None = Query(default=None),
    platform: str | None = Query(default=None),
    prompt_id: int | None = Query(default=None),
    competitor_id: int | None = Query(default=None),
    audience: str | None = Query(default=None),
    location: str | None = Query(default=None),
    intent: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if property_id is not None and db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    try:
        content, filename = build_sov_csv(
            db, property_id, days,
            **_sov_filters(topic_id, platform, prompt_id, competitor_id, audience, location, intent, priority),
        )
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
