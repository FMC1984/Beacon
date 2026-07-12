"""Thin wrappers over the two Google APIs Beacon pulls from.

Each function takes an access token and returns plain Python data; the sync
service owns all database writes. HTTP goes through _request so tests can
monkeypatch one seam.
"""

from datetime import date

import httpx

from app.services.google_sync.oauth import GoogleOAuthError

ADMIN_API = "https://analyticsadmin.googleapis.com/v1beta"
DATA_API = "https://analyticsdata.googleapis.com/v1beta"
GSC_API = "https://www.googleapis.com/webmasters/v3"


def _request(method: str, url: str, access_token: str, json: dict | None = None) -> dict:
    resp = httpx.request(
        method,
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        json=json,
        timeout=60,
    )
    if resp.status_code >= 400:
        raise GoogleOAuthError(f"Google returned {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def list_ga4_properties(access_token: str) -> list[dict]:
    """Every GA4 property the account can read: [{id, name}]."""
    out: list[dict] = []
    url = f"{ADMIN_API}/accountSummaries?pageSize=200"
    while url:
        body = _request("GET", url, access_token)
        for account in body.get("accountSummaries", []):
            for prop in account.get("propertySummaries", []):
                out.append(
                    {
                        "id": prop["property"],  # "properties/123456789"
                        "name": f"{prop.get('displayName', prop['property'])} "
                        f"({account.get('displayName', '')})".strip(),
                    }
                )
        token = body.get("nextPageToken")
        url = f"{ADMIN_API}/accountSummaries?pageSize=200&pageToken={token}" if token else None
    return out


def list_gsc_sites(access_token: str) -> list[dict]:
    body = _request("GET", f"{GSC_API}/sites", access_token)
    return [
        {"id": e["siteUrl"], "name": e["siteUrl"]}
        for e in body.get("siteEntry", [])
        if e.get("permissionLevel") != "siteUnverifiedUser"
    ]


def ga4_run_report(
    access_token: str, property_resource: str, start: date, end: date
) -> list[dict]:
    """Daily sessions by source/medium - the same shape as the CSV exports, so
    the classifier and everything downstream behave identically."""
    body = _request(
        "POST",
        f"{DATA_API}/{property_resource}:runReport",
        access_token,
        json={
            "dateRanges": [{"startDate": start.isoformat(), "endDate": end.isoformat()}],
            "dimensions": [
                {"name": "date"},
                {"name": "sessionSource"},
                {"name": "sessionMedium"},
            ],
            "metrics": [
                {"name": "sessions"},
                {"name": "engagedSessions"},
                {"name": "totalUsers"},
                {"name": "keyEvents"},
            ],
            "limit": 100000,
        },
    )
    rows = []
    for r in body.get("rows", []):
        dims = [d["value"] for d in r["dimensionValues"]]
        mets = [m["value"] for m in r["metricValues"]]
        rows.append(
            {
                "date": date(int(dims[0][:4]), int(dims[0][4:6]), int(dims[0][6:8])),
                "session_source": dims[1] or "(not set)",
                "session_medium": dims[2] or "(not set)",
                "sessions": int(float(mets[0] or 0)),
                "engaged_sessions": int(float(mets[1] or 0)),
                "total_users": int(float(mets[2] or 0)),
                "key_events": int(float(mets[3] or 0)),
            }
        )
    return rows


def gsc_query(access_token: str, site_url: str, start: date, end: date) -> list[dict]:
    """Daily query/page performance. Includes the page dimension, which the
    manual Queries export lacks."""
    from urllib.parse import quote

    body = _request(
        "POST",
        f"{GSC_API}/sites/{quote(site_url, safe='')}/searchAnalytics/query",
        access_token,
        json={
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions": ["date", "query", "page"],
            "rowLimit": 25000,
        },
    )
    rows = []
    for r in body.get("rows", []):
        d, query, page = r["keys"]
        rows.append(
            {
                "date": date.fromisoformat(d),
                "query": query,
                "page": page,
                "clicks": int(r.get("clicks", 0)),
                "impressions": int(r.get("impressions", 0)),
                "ctr": float(r.get("ctr", 0.0)),
                "position": float(r.get("position", 0.0)),
            }
        )
    return rows
