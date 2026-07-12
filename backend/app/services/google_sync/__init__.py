"""Google auto-sync: OAuth connect flow + GA4 Data API / Search Console API
pullers. The ONLY module that talks to Google. Synced rows carry sync_job_id
provenance (the API-side mirror of upload_id), flow through the same
classifier and replace-on-overlap semantics as CSV uploads, and trigger the
same RAG sync - everything downstream is unchanged.

Fixed product language (per the Phase 3 decision): this is "Scheduled sync" /
"Auto-sync" with a "Last updated" timestamp - never described as real-time
(GA4 data itself lags a day or two).
"""

from app.services.google_sync.oauth import (
    auth_url,
    exchange_code,
    refresh_access_token,
    sign_state,
    verify_state,
)
from app.services.google_sync.sync import run_google_sync

__all__ = [
    "auth_url",
    "exchange_code",
    "refresh_access_token",
    "sign_state",
    "verify_state",
    "run_google_sync",
]
