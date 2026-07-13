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
# Business Profile is split across APIs: accounts + location listing live on the
# newer v1 endpoints, but reviews are ONLY on the legacy My Business v4 endpoint
# (there is no v1 reviews resource). Both require the Cloud project to be
# allowlisted for Business Profile API access.
GBP_ACCOUNTS_API = "https://mybusinessaccountmanagement.googleapis.com/v1"
GBP_INFO_API = "https://mybusinessbusinessinformation.googleapis.com/v1"
GBP_REVIEWS_API = "https://mybusiness.googleapis.com/v4"

# GBP returns star ratings as words; Beacon stores numbers. "STAR_RATING_UNSPECIFIED"
# maps to None (a real "no rating"), never 0.
_GBP_STAR_TO_NUMBER = {
    "ONE": 1.0,
    "TWO": 2.0,
    "THREE": 3.0,
    "FOUR": 4.0,
    "FIVE": 5.0,
}


_GEO_UNSET = {"(not set)", "(not provided)", "(other)"}


def _geo_value(raw: str | None) -> str | None:
    """GA4 city/region: treat its unresolved placeholders as NULL (Unknown),
    matching the CSV parser so synced and uploaded rows aggregate the same."""
    value = (raw or "").strip()
    if not value or value.lower() in _GEO_UNSET:
        return None
    return value


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
            # landingPagePlusQueryString lets AI Query Signals join an AI-
            # referred session's landing page to Search Console pages (the CSV
            # source/medium export lacked it).
            "dimensions": [
                {"name": "date"},
                {"name": "sessionSource"},
                {"name": "sessionMedium"},
                {"name": "landingPagePlusQueryString"},
                # City + region feed the Audience report. GA4 returns only
                # non-empty combinations, so this adds rows but not empty noise.
                {"name": "city"},
                {"name": "region"},
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
        landing = dims[3]
        rows.append(
            {
                "date": date(int(dims[0][:4]), int(dims[0][4:6]), int(dims[0][6:8])),
                "session_source": dims[1] or "(not set)",
                "session_medium": dims[2] or "(not set)",
                "landing_page": landing if landing and landing != "(not set)" else None,
                "city": _geo_value(dims[4]),
                "region": _geo_value(dims[5]),
                "sessions": int(float(mets[0] or 0)),
                "engaged_sessions": int(float(mets[1] or 0)),
                "total_users": int(float(mets[2] or 0)),
                "key_events": int(float(mets[3] or 0)),
            }
        )
    return rows


def ga4_events_report(
    access_token: str, property_resource: str, start: date, end: date
) -> list[dict]:
    """Daily event counts by event name (page_view, scroll, click, ...), the
    same breakdown as GA4's Events report but per day so it windows cleanly."""
    body = _request(
        "POST",
        f"{DATA_API}/{property_resource}:runReport",
        access_token,
        json={
            "dateRanges": [{"startDate": start.isoformat(), "endDate": end.isoformat()}],
            "dimensions": [{"name": "date"}, {"name": "eventName"}],
            "metrics": [{"name": "eventCount"}, {"name": "totalUsers"}],
            "limit": 100000,
        },
    )
    rows = []
    for r in body.get("rows", []):
        dims = [d["value"] for d in r["dimensionValues"]]
        mets = [m["value"] for m in r["metricValues"]]
        if not dims[1]:
            continue
        rows.append(
            {
                "date": date(int(dims[0][:4]), int(dims[0][4:6]), int(dims[0][6:8])),
                "event_name": dims[1],
                "event_count": int(float(mets[0] or 0)),
                "total_users": int(float(mets[1] or 0)),
            }
        )
    return rows


def _gbp_date(ts: str | None) -> date | None:
    """GBP timestamps are RFC3339 (2021-01-05T12:34:56.000Z); keep the calendar
    date, which is all Beacon's review_date stores."""
    if not ts:
        return None
    try:
        return date.fromisoformat(ts[:10])
    except ValueError:
        return None


def list_gbp_locations(access_token: str) -> list[dict]:
    """Every Business Profile location the account manages: [{id, name}], where
    id is the full 'accounts/A/locations/L' resource used as the reviews parent."""
    out: list[dict] = []
    read_mask = "readMask=name,title,storefrontAddress"
    accounts = _request(
        "GET", f"{GBP_ACCOUNTS_API}/accounts?pageSize=100", access_token
    )
    for account in accounts.get("accounts", []):
        acct = account["name"]  # "accounts/123"
        url = f"{GBP_INFO_API}/{acct}/locations?pageSize=100&{read_mask}"
        while url:
            body = _request("GET", url, access_token)
            for loc in body.get("locations", []):
                # Location name is "locations/456"; the v4 reviews path needs it
                # under its account: "accounts/123/locations/456".
                loc_name = loc["name"].split("/")[-1]
                addr = loc.get("storefrontAddress", {})
                locality = addr.get("locality")
                title = loc.get("title", loc_name)
                out.append(
                    {
                        "id": f"{acct}/locations/{loc_name}",
                        "name": f"{title} ({locality})" if locality else title,
                    }
                )
            token = body.get("nextPageToken")
            url = (
                f"{GBP_INFO_API}/{acct}/locations?pageSize=100&{read_mask}&pageToken={token}"
                if token
                else None
            )
    return out


def gbp_reviews(access_token: str, location_resource: str) -> list[dict]:
    """All reviews for one location, normalized to Beacon's review shape. The
    reviews API is not date-windowed, so this pulls the full set and the sync
    upserts by review id."""
    out: list[dict] = []
    base = f"{GBP_REVIEWS_API}/{location_resource}/reviews?pageSize=200"
    url = base
    while url:
        body = _request("GET", url, access_token)
        for rv in body.get("reviews", []):
            reviewer = rv.get("reviewer", {})
            reply = rv.get("reviewReply") or {}
            external_id = rv.get("reviewId") or rv.get("name", "").split("/")[-1] or None
            out.append(
                {
                    "external_review_id": external_id,
                    "author_name": reviewer.get("displayName"),
                    "rating": _GBP_STAR_TO_NUMBER.get(rv.get("starRating")),
                    "title": None,
                    "body": rv.get("comment") or "",
                    "review_date": _gbp_date(rv.get("createTime")),
                    "response_text": reply.get("comment"),
                    "response_date": _gbp_date(reply.get("updateTime")),
                    "source_url": None,
                }
            )
        token = body.get("nextPageToken")
        url = f"{base}&pageToken={token}" if token else None
    return out


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
