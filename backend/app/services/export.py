"""Data export: bundle the real ingested rows for a property (or the whole
portfolio) into a ZIP of CSV files plus a manifest.

Everything here is a straight dump of what was ingested - no derived metrics,
no fabrication. The manifest carries the AI-traffic undercount disclosure
because the GA4 export includes AI-referral columns, and that disclosure must
travel with every AI traffic figure (see app/constants.py)."""

import csv
import io
import re
import zipfile
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.constants import AI_TRAFFIC_DISCLOSURE, APP_VERSION
from app.models import (
    Company,
    CRMLead,
    GA4SessionsDaily,
    GBPMetricsDaily,
    GSCPerformanceDaily,
    PaidMediaDaily,
    Property,
)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "export"


def _cell(value) -> str:
    """CSV cell rendering: None -> empty string, everything else stringified.
    Dates/datetimes serialize via isoformat so the output is spreadsheet-safe."""
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "value"):  # enum (LeadStatus)
        return value.value
    return str(value)


# (filename, model, columns, order_by) for each dataset. Columns are listed
# explicitly so the export stays stable if a model gains internal fields.
_DATASETS = [
    (
        "ga4_sessions_daily.csv",
        GA4SessionsDaily,
        [
            "date", "session_source", "session_medium", "session_campaign",
            "landing_page", "sessions", "engaged_sessions", "total_users",
            "key_events", "is_ai_referral", "ai_platform", "source_line",
        ],
        lambda m: (m.date, m.id),
    ),
    (
        "gsc_performance_daily.csv",
        GSCPerformanceDaily,
        ["date", "query", "page", "clicks", "impressions", "ctr", "position", "source_line"],
        lambda m: (m.date, m.id),
    ),
    (
        "gbp_metrics_daily.csv",
        GBPMetricsDaily,
        [
            "date", "search_impressions", "maps_impressions", "website_clicks",
            "calls", "direction_requests", "source_line",
        ],
        lambda m: (m.date, m.id),
    ),
    (
        "paid_media_daily.csv",
        PaidMediaDaily,
        [
            "date", "platform", "campaign_name", "impressions", "clicks",
            "spend", "conversions", "source_line",
        ],
        lambda m: (m.date, m.id),
    ),
    (
        "crm_leads.csv",
        CRMLead,
        [
            "external_lead_id", "lead_source_raw", "lead_source_normalized",
            "status", "first_contact_date", "tour_date", "application_date",
            "lease_signed_date", "move_in_date",
        ],
        lambda m: (m.first_contact_date, m.id),
    ),
]

_PROPERTY_COLUMNS = [
    "id", "name", "slug", "external_code", "city", "state",
    "unit_count", "website_url", "is_active", "created_at",
]


def _write_csv(columns: list[str], rows: list) -> tuple[str, int]:
    buf = io.StringIO()
    writer = csv.writer(buf)
    # Every daily-data CSV leads with the property so a portfolio export stays
    # unambiguous when concatenated; property.csv is keyed by id already.
    lead = [] if columns is _PROPERTY_COLUMNS else ["property"]
    writer.writerow(lead + columns)
    count = 0
    for prop_name, obj in rows:
        base = [] if columns is _PROPERTY_COLUMNS else [prop_name]
        writer.writerow(base + [_cell(getattr(obj, c)) for c in columns])
        count += 1
    return buf.getvalue(), count


def build_export(
    db: Session,
    property_id: int | None,
    company_id: int | None = None,
    unassigned: bool = False,
) -> tuple[bytes, str]:
    """Return (zip_bytes, filename). Scope precedence: a single property, then
    unassigned (no-company) properties, then a company's properties, else the
    whole portfolio."""
    company = None
    if property_id is not None:
        props = [db.get(Property, property_id)]
        if props[0] is None:
            raise ValueError("Property not found.")
    elif unassigned:
        props = (
            db.query(Property)
            .filter(Property.company_id.is_(None))
            .order_by(Property.name)
            .all()
        )
    elif company_id is not None:
        company = db.get(Company, company_id)
        if company is None:
            raise ValueError("Company not found.")
        props = (
            db.query(Property)
            .filter(Property.company_id == company_id)
            .order_by(Property.name)
            .all()
        )
    else:
        props = (
            db.query(Property).order_by(Property.name).all()
        )

    prop_by_id = {p.id: p for p in props}
    ids = list(prop_by_id.keys())

    manifest_lines = [
        "Beacon data export",
        f"Beacon version: {APP_VERSION}",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "Scope: " + _scope_label(property_id, company, unassigned, props),
        "",
        "This bundle contains the raw rows Beacon ingested, exactly as stored.",
        "No metrics are derived or estimated here.",
        "",
        "AI traffic disclosure (applies to ga4_sessions_daily.csv):",
        f"  {AI_TRAFFIC_DISCLOSURE}",
        "",
        "Files:",
    ]

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # properties.csv
        prop_rows = [(p.name, p) for p in props]
        content, count = _write_csv(_PROPERTY_COLUMNS, prop_rows)
        zf.writestr("properties.csv", content)
        manifest_lines.append(f"  properties.csv: {count} row(s)")

        for filename, model, columns, order_key in _DATASETS:
            q = db.query(model)
            if ids:
                q = q.filter(model.property_id.in_(ids))
            else:
                q = q.filter(False)
            objs = sorted(q.all(), key=order_key)
            rows = [(prop_by_id[o.property_id].name, o) for o in objs]
            content, count = _write_csv(columns, rows)
            zf.writestr(filename, content)
            manifest_lines.append(f"  {filename}: {count} row(s)")

        zf.writestr("manifest.txt", "\n".join(manifest_lines) + "\n")

    if property_id is not None:
        name = f"beacon-export-{_slugify(props[0].name)}.zip"
    elif unassigned:
        name = "beacon-export-unassigned.zip"
    elif company is not None:
        name = f"beacon-export-{company.slug}.zip"
    else:
        name = "beacon-export-portfolio.zip"
    return zip_buf.getvalue(), name


def _scope_label(property_id, company, unassigned, props) -> str:
    if property_id is not None:
        return f"property - {props[0].name}"
    if unassigned:
        return f"unassigned properties ({len(props)} with no company)"
    if company is not None:
        return f"company - {company.name} ({len(props)} property(ies))"
    return "portfolio (all properties)"
