"""Sync execution: pull the trailing window from Google, write rows with
sync_job_id provenance, stamp AI referral classification, trigger RAG sync.

Replace-on-overlap by date, exactly like uploads: rows for the property whose
date falls inside the pulled window are replaced wholesale, so re-syncing is
idempotent and coexists with manual CSV uploads covering other dates.
"""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.extensions.hooks import trigger_rag_sync
from app.models import (
    DataConnection,
    GA4SessionsDaily,
    GSCPerformanceDaily,
    OAuthStatus,
    SourceType,
    SyncJob,
    SyncJobStatus,
    SyncStatus,
)
from app.services.classifier import get_classifier
from app.services.google_sync import gapi
from app.services.google_sync.oauth import GoogleOAuthError, refresh_access_token
from app.services.ingestion.reviews import upsert_reviews

# Provider label stored on reviews pulled from Google Business Profile. Matches
# the manual-import default so both paths dedup against the same rows.
GBP_PROVIDER = "google"

_REPORT_TYPES = {
    SourceType.GA4: "ga4_sessions_by_source_medium",
    SourceType.GSC: "gsc_search_analytics_query_page",
    SourceType.GBP: "gbp_location_reviews",
}


def _window(today: date | None = None) -> tuple[date, date]:
    end = today or date.today()
    return end - timedelta(days=settings.google_sync_days - 1), end


def _write_ga4(db: Session, conn: DataConnection, job: SyncJob, rows: list[dict], lo: date, hi: date) -> int:
    replaced = (
        db.query(GA4SessionsDaily)
        .filter(
            GA4SessionsDaily.property_id == conn.property_id,
            GA4SessionsDaily.date >= lo,
            GA4SessionsDaily.date <= hi,
        )
        .delete(synchronize_session=False)
    )
    classifier = get_classifier()
    for r in rows:
        platform = classifier.classify(r["session_source"])
        db.add(
            GA4SessionsDaily(
                property_id=conn.property_id,
                sync_job_id=job.id,
                date=r["date"],
                session_source=r["session_source"],
                session_medium=r["session_medium"],
                landing_page=r.get("landing_page"),
                sessions=r["sessions"],
                engaged_sessions=r["engaged_sessions"],
                total_users=r["total_users"],
                key_events=r["key_events"],
                is_ai_referral=platform is not None,
                ai_platform=platform,
            )
        )
    job.rows_updated = replaced
    return len(rows)


def _write_gsc(db: Session, conn: DataConnection, job: SyncJob, rows: list[dict], lo: date, hi: date) -> int:
    replaced = (
        db.query(GSCPerformanceDaily)
        .filter(
            GSCPerformanceDaily.property_id == conn.property_id,
            GSCPerformanceDaily.date >= lo,
            GSCPerformanceDaily.date <= hi,
        )
        .delete(synchronize_session=False)
    )
    for r in rows:
        db.add(
            GSCPerformanceDaily(
                property_id=conn.property_id,
                sync_job_id=job.id,
                date=r["date"],
                query=r["query"],
                page=r["page"],
                clicks=r["clicks"],
                impressions=r["impressions"],
                ctr=r["ctr"],
                position=r["position"],
            )
        )
    job.rows_updated = replaced
    return len(rows)


def _write_gbp_reviews(db: Session, conn: DataConnection, job: SyncJob, reviews: list[dict]) -> int:
    """Upsert Business Profile reviews as PropertyReview rows, deduped by
    (provider, external_review_id) exactly like the manual import. Reviews are
    not date-windowed, so this updates in place rather than replace-by-date."""
    rows = [{**rv, "provider": GBP_PROVIDER} for rv in reviews]
    result = upsert_reviews(db, conn.property_id, rows)
    job.rows_updated = result["updated"]
    return result["imported"]


def run_google_sync(db: Session, connection_id: int, today: date | None = None) -> SyncJob:
    """Execute one sync for one connection. Raises ValueError on a connection
    that is not ready; Google/API failures are recorded on the job AND the
    connection, then re-raised as GoogleOAuthError."""
    conn = db.get(DataConnection, connection_id)
    if conn is None:
        raise ValueError("Connection not found.")
    if conn.oauth_status != OAuthStatus.CONNECTED or not conn.refresh_token:
        raise ValueError("Connection is not authorized. Connect Google first.")
    if not conn.resource_id:
        raise ValueError(
            "No source selected. Pick which GA4 property or Search Console "
            "site this connection pulls from."
        )

    lo, hi = _window(today)
    # Reviews are not date-windowed; only the daily metrics sources carry a
    # window on the job.
    windowed = conn.source_type in (SourceType.GA4, SourceType.GSC)
    job = SyncJob(
        connection_id=conn.id,
        source_type=conn.source_type,
        report_type=_REPORT_TYPES.get(conn.source_type),
        endpoint=conn.resource_id,
        date_start=lo if windowed else None,
        date_end=hi if windowed else None,
    )
    db.add(job)
    db.flush()

    conn.sync_status = SyncStatus.SYNCING
    try:
        token = refresh_access_token(conn.refresh_token)
        if conn.source_type == SourceType.GA4:
            rows = gapi.ga4_run_report(token, conn.resource_id, lo, hi)
            job.rows_imported = _write_ga4(db, conn, job, rows, lo, hi)
        elif conn.source_type == SourceType.GSC:
            rows = gapi.gsc_query(token, conn.resource_id, lo, hi)
            job.rows_imported = _write_gsc(db, conn, job, rows, lo, hi)
        elif conn.source_type == SourceType.GBP:
            reviews = gapi.gbp_reviews(token, conn.resource_id)
            job.rows_imported = _write_gbp_reviews(db, conn, job, reviews)
        else:
            raise ValueError(f"Unsupported source_type {conn.source_type}.")
    except GoogleOAuthError as exc:
        job.status = SyncJobStatus.FAILED
        job.error_message = str(exc)[:1000]
        job.completed_at = datetime.now(timezone.utc)
        conn.sync_status = SyncStatus.ERROR
        conn.error_message = str(exc)[:1000]
        if "invalid_grant" in str(exc):
            conn.oauth_status = OAuthStatus.EXPIRED
        db.commit()
        raise

    job.status = SyncJobStatus.COMPLETED
    job.completed_at = datetime.now(timezone.utc)
    conn.sync_status = SyncStatus.IDLE
    conn.error_message = None
    conn.last_sync_at = datetime.now(timezone.utc)
    db.commit()

    # GBP feeds the review pipeline, so its RAG sync uses the "reviews" source
    # (refreshes per-review chunks + the Review Intelligence chunk), not "gbp".
    rag_source = "reviews" if conn.source_type == SourceType.GBP else conn.source_type.value
    trigger_rag_sync(
        db,
        property_id=conn.property_id,
        source=rag_source,
        reason=f"google_sync_{conn.source_type.value}",
    )
    db.commit()
    return job
