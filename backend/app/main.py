import secrets

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings

from app.routers import (
    admin,
    ai_query_signals,
    ai_visibility,
    companies,
    competitor_intelligence,
    competitors,
    content,
    briefing,
    content_changes,
    content_intelligence,
    dashboard,
    export,
    google,
    health,
    opportunities,
    nora,
    properties,
    property_context,
    reports_v2,
    review_intelligence,
    reviews,
    uploads,
)

app = FastAPI(title="Beacon", version="0.1.0")


@app.middleware("http")
async def require_access_key(request: Request, call_next):
    """Shared-key gate for hosted deployments. Inert when BEACON_ACCESS_KEY is
    unset (local single-user use). /api/health stays open so the key screen and
    Render's health checks can reach the server; OPTIONS passes so CORS
    preflights (which never carry custom headers) keep working."""
    if (
        settings.access_key
        and request.url.path.startswith("/api")
        # /api/google/callback: Google's browser redirect cannot carry the
        # key header; the endpoint verifies its own HMAC-signed state instead.
        and request.url.path not in ("/api/health", "/api/google/callback")
        # /api/briefing/shared/<token>: the public share route (Phase 17D).
        # The unguessable token IS the authorization; the payload is a frozen,
        # client-safe snapshot. GET only - share/revoke stay key-protected.
        and not (
            request.method == "GET"
            and request.url.path.startswith("/api/briefing/shared/")
        )
        and request.method != "OPTIONS"
        and not secrets.compare_digest(
            request.headers.get("x-beacon-key", ""), settings.access_key
        )
    ):
        return JSONResponse(
            status_code=401, content={"detail": "Missing or invalid access key."}
        )
    return await call_next(request)


# Local dev origins plus any hosted origins from BEACON_CORS_ORIGINS.
_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3100",
    "http://127.0.0.1:3100",
] + [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(companies.router, prefix="/api")
app.include_router(properties.router, prefix="/api")
app.include_router(uploads.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(nora.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(content.router, prefix="/api")
app.include_router(content_intelligence.router, prefix="/api")
app.include_router(ai_query_signals.router, prefix="/api")
app.include_router(ai_visibility.router, prefix="/api")
app.include_router(competitors.router, prefix="/api")
app.include_router(competitor_intelligence.router, prefix="/api")
app.include_router(opportunities.router, prefix="/api")
app.include_router(property_context.router, prefix="/api")
app.include_router(reviews.router, prefix="/api")
app.include_router(review_intelligence.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(google.router, prefix="/api")
app.include_router(reports_v2.router, prefix="/api")
app.include_router(content_changes.router, prefix="/api")
app.include_router(briefing.router, prefix="/api")


@app.on_event("startup")
async def start_google_autosync():
    """Scheduled sync: when BEACON_GOOGLE_AUTOSYNC is on, re-pull every
    authorized Google connection once a day. Failures are recorded on the
    connection (visible in the UI) and never crash the loop."""
    if not settings.google_autosync:
        return
    import asyncio

    async def loop():
        from app.db import SessionLocal
        from app.models import DataConnection, OAuthStatus
        from app.services.google_sync import run_google_sync
        from app.services.rag_sync_service import drain_queue

        while True:
            db = SessionLocal()
            try:
                ready = (
                    db.query(DataConnection)
                    .filter(
                        DataConnection.oauth_status == OAuthStatus.CONNECTED,
                        DataConnection.resource_id.isnot(None),
                    )
                    .all()
                )
                for conn in ready:
                    try:
                        run_google_sync(db, conn.id)
                    except Exception:
                        pass  # recorded on the connection by run_google_sync
                if ready and settings.rag_autosync:
                    drain_queue()
            finally:
                db.close()
            await asyncio.sleep(24 * 60 * 60)

    asyncio.create_task(loop())


@app.on_event("startup")
async def start_ai_visibility_autorun():
    """Weekly scheduled AI Visibility run: execute each property's active
    standing prompts and snapshot the score, so visibility accumulates a real
    trend. Costs OpenAI budget, so gated behind BEACON_AI_VISIBILITY_AUTORUN.
    The per-property daily budget still caps spend; failures never crash the
    loop."""
    if not settings.ai_visibility_autorun:
        return
    import asyncio

    async def loop():
        from app.db import SessionLocal
        from app.models import AIVisibilityPrompt, Property
        from app.services.ai_visibility.schedule import run_standing_prompts
        from app.services.rag_sync_service import drain_queue

        while True:
            db = SessionLocal()
            try:
                property_ids = [
                    pid
                    for (pid,) in db.query(AIVisibilityPrompt.property_id)
                    .filter(AIVisibilityPrompt.active.is_(True))
                    .distinct()
                    .all()
                ]
                for pid in property_ids:
                    try:
                        run_standing_prompts(db, pid)
                    except Exception:
                        pass  # a bad property never aborts the weekly batch
                if property_ids and settings.rag_autosync:
                    drain_queue()
            finally:
                db.close()
            await asyncio.sleep(7 * 24 * 60 * 60)

    asyncio.create_task(loop())
