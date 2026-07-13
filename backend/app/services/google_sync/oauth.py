"""Google OAuth 2.0 flow, implemented directly over httpx (no Google SDK).

State is HMAC-signed with the client secret so the /callback endpoint (which
must be reachable without Beacon's access key - Google's redirect cannot carry
custom headers) only accepts flows this server started. Tokens are exchanged
server-side; the browser never sees them.
"""

import hashlib
import hmac
import time
from urllib.parse import urlencode

import httpx

from app.config import settings

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"

SCOPES = [
    "https://www.googleapis.com/auth/analytics.readonly",
    "https://www.googleapis.com/auth/webmasters.readonly",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]

# Restricted scope for reading Business Profile reviews. Requested ONLY when the
# GBP connector is enabled (settings.google_gbp_enabled): before Google has
# allowlisted the project for the Business Profile API, including this scope in
# the shared consent screen makes the whole GA4/GSC connect fail, so it stays
# out of the default set.
GBP_SCOPE = "https://www.googleapis.com/auth/business.manage"

STATE_TTL_SECONDS = 900


def current_scopes() -> list[str]:
    """The scopes this server requests, including GBP only when enabled."""
    scopes = list(SCOPES)
    if settings.google_gbp_enabled:
        scopes.append(GBP_SCOPE)
    return scopes


class GoogleOAuthError(RuntimeError):
    pass


def _post_form(url: str, data: dict) -> dict:
    """Form-encoded POST. Isolated so tests can monkeypatch it."""
    resp = httpx.post(url, data=data, timeout=30)
    if resp.status_code >= 400:
        raise GoogleOAuthError(f"Google returned {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def _get_json(url: str, access_token: str) -> dict:
    resp = httpx.get(
        url, headers={"Authorization": f"Bearer {access_token}"}, timeout=30
    )
    if resp.status_code >= 400:
        raise GoogleOAuthError(f"Google returned {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def _sig(payload: str) -> str:
    return hmac.new(
        settings.google_client_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()


def sign_state(property_id: int, now: int | None = None) -> str:
    ts = now if now is not None else int(time.time())
    payload = f"{property_id}.{ts}"
    return f"{payload}.{_sig(payload)}"


def verify_state(state: str, now: int | None = None) -> int:
    """Returns the property_id if the state is authentic and fresh."""
    try:
        prop_str, ts_str, sig = state.split(".")
        payload = f"{prop_str}.{ts_str}"
    except ValueError:
        raise GoogleOAuthError("Malformed state.")
    if not hmac.compare_digest(sig, _sig(payload)):
        raise GoogleOAuthError("State signature mismatch.")
    age = (now if now is not None else int(time.time())) - int(ts_str)
    if age > STATE_TTL_SECONDS or age < -60:
        raise GoogleOAuthError("State expired; start the connect flow again.")
    return int(prop_str)


def auth_url(property_id: int) -> str:
    if not settings.google_client_id or not settings.google_client_secret:
        raise GoogleOAuthError(
            "Google OAuth is not configured. Set BEACON_GOOGLE_CLIENT_ID and "
            "BEACON_GOOGLE_CLIENT_SECRET (see README section on Google sync)."
        )
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(current_scopes()),
        "access_type": "offline",
        # Force the consent screen so Google always returns a refresh_token,
        # even on re-connect.
        "prompt": "consent",
        "state": sign_state(property_id),
    }
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    """Authorization code -> {access_token, refresh_token, expires_in, ...}."""
    return _post_form(
        TOKEN_ENDPOINT,
        {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": settings.google_redirect_uri,
        },
    )


def refresh_access_token(refresh_token: str) -> str:
    body = _post_form(
        TOKEN_ENDPOINT,
        {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    return body["access_token"]


def account_email(access_token: str) -> str:
    try:
        return _get_json(USERINFO_ENDPOINT, access_token).get("email", "Google account")
    except GoogleOAuthError:
        return "Google account"


def revoke(refresh_token: str) -> None:
    """Best effort - disconnecting locally must succeed even if Google is
    unreachable or the token is already dead."""
    try:
        httpx.post(REVOKE_ENDPOINT, data={"token": refresh_token}, timeout=15)
    except Exception:
        pass
