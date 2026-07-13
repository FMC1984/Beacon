"""Google connection endpoints: OAuth connect/callback, resource selection,
manual sync, status, disconnect.

/callback is exempt from the access-key middleware (Google's browser redirect
cannot carry the header); it is protected instead by the HMAC-signed state,
and the authorization code it receives is useless without the client secret.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import DataConnection, OAuthStatus, Property, SourceType
from app.services.google_sync import auth_url, exchange_code, run_google_sync, verify_state
from app.services.google_sync import gapi
from app.services.google_sync.oauth import (
    GoogleOAuthError,
    account_email,
    refresh_access_token,
    revoke,
)
from app.services.rag_sync_service import drain_queue

router = APIRouter(prefix="/google", tags=["google"])

# GA4 + GSC always; GBP (reviews) only when enabled, because its restricted
# scope must not join the shared consent screen until the project is approved.
def _google_sources() -> tuple[SourceType, ...]:
    base = (SourceType.GA4, SourceType.GSC)
    return base + (SourceType.GBP,) if settings.google_gbp_enabled else base


def _conn_out(c: DataConnection) -> dict:
    return {
        "id": c.id,
        "property_id": c.property_id,
        "source_type": c.source_type.value,
        "account_name": c.account_name,
        "resource_id": c.resource_id,
        "resource_name": c.resource_name,
        "oauth_status": c.oauth_status.value,
        "sync_status": c.sync_status.value,
        "last_sync_at": c.last_sync_at.isoformat() if c.last_sync_at else None,
        "error_message": c.error_message,
    }


@router.get("/status")
def status(property_id: int, db: Session = Depends(get_db)):
    """Connection state for a property, plus whether OAuth is configured at
    all (the frontend uses this to show setup instructions honestly)."""
    conns = (
        db.query(DataConnection)
        .filter(
            DataConnection.property_id == property_id,
            DataConnection.source_type.in_(_google_sources()),
        )
        .order_by(DataConnection.source_type)
        .all()
    )
    return {
        "configured": bool(settings.google_client_id and settings.google_client_secret),
        "gbp_enabled": settings.google_gbp_enabled,
        "connections": [_conn_out(c) for c in conns],
    }


@router.get("/connect")
def connect(property_id: int, db: Session = Depends(get_db)):
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    try:
        return {"auth_url": auth_url(property_id)}
    except GoogleOAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/callback")
def callback(state: str, code: str = "", error: str = "", db: Session = Depends(get_db)):
    """Google redirects the operator's browser here. On success, one
    connection row per source (GA4 + GSC, plus GBP when enabled) is created or
    refreshed for the property encoded in the signed state, then the browser is
    sent back to the frontend."""
    frontend = settings.frontend_url.rstrip("/")
    try:
        property_id = verify_state(state)
    except GoogleOAuthError as exc:
        return RedirectResponse(f"{frontend}/uploads?google=error&reason={exc}")
    if error or not code:
        return RedirectResponse(f"{frontend}/uploads?google=error&reason={error or 'no code'}")

    try:
        tokens = exchange_code(code)
    except GoogleOAuthError as exc:
        return RedirectResponse(f"{frontend}/uploads?google=error&reason={str(exc)[:120]}")

    email = account_email(tokens["access_token"])
    refresh = tokens.get("refresh_token")
    for source in _google_sources():
        conn = (
            db.query(DataConnection)
            .filter_by(property_id=property_id, source_type=source)
            .first()
        )
        if conn is None:
            conn = DataConnection(
                property_id=property_id,
                source_type=source,
                account_name=email,
                external_account_id=email,
            )
            db.add(conn)
        conn.account_name = email
        conn.external_account_id = email
        # prompt=consent means a refresh token normally arrives; keep the old
        # one if Google omitted it rather than wiping a working connection.
        if refresh:
            conn.refresh_token = refresh
        conn.oauth_status = OAuthStatus.CONNECTED
        conn.error_message = None
    db.commit()
    return RedirectResponse(f"{frontend}/uploads?google=connected")


@router.get("/connections/{connection_id}/resources")
def list_resources(connection_id: int, db: Session = Depends(get_db)):
    """The GA4 properties, GSC sites, or GBP locations the connected account can
    read, so the operator picks which one feeds this Beacon property."""
    conn = db.get(DataConnection, connection_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found.")
    if conn.oauth_status != OAuthStatus.CONNECTED or not conn.refresh_token:
        raise HTTPException(status_code=400, detail="Connection is not authorized.")
    try:
        token = refresh_access_token(conn.refresh_token)
        if conn.source_type == SourceType.GA4:
            return {"resources": gapi.list_ga4_properties(token)}
        if conn.source_type == SourceType.GSC:
            return {"resources": gapi.list_gsc_sites(token)}
        return {"resources": gapi.list_gbp_locations(token)}
    except GoogleOAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


class ResourceChoice(BaseModel):
    resource_id: str
    resource_name: str | None = None


@router.post("/connections/{connection_id}/resource")
def set_resource(connection_id: int, choice: ResourceChoice, db: Session = Depends(get_db)):
    conn = db.get(DataConnection, connection_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found.")
    conn.resource_id = choice.resource_id
    conn.resource_name = choice.resource_name or choice.resource_id
    db.commit()
    return _conn_out(conn)


@router.post("/connections/{connection_id}/sync")
def sync_now(
    connection_id: int, background: BackgroundTasks, db: Session = Depends(get_db)
):
    try:
        job = run_google_sync(db, connection_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except GoogleOAuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    if settings.rag_autosync:
        background.add_task(drain_queue)
    return {
        "job_id": job.id,
        "status": job.status.value,
        "rows_imported": job.rows_imported,
        "rows_replaced": job.rows_updated,
        "date_start": job.date_start.isoformat(),
        "date_end": job.date_end.isoformat(),
    }


@router.delete("/connections/{connection_id}")
def disconnect(connection_id: int, db: Session = Depends(get_db)):
    """Remove the connection. Synced DATA stays (it is real history with
    sync_job provenance); only the credential and mapping are removed."""
    conn = db.get(DataConnection, connection_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Connection not found.")
    if conn.refresh_token:
        revoke(conn.refresh_token)
    conn.refresh_token = None
    conn.resource_id = None
    conn.resource_name = None
    conn.oauth_status = OAuthStatus.REVOKED
    db.commit()
    return {"ok": True}
