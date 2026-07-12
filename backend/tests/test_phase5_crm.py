from datetime import date

from app.adapters import ADAPTERS
from app.adapters.yardi_adapter import PLACEHOLDER_WARNING, YardiAdapter
from app.models import CRMLead, LeadStatus, Upload, UploadStatus
from tests.conftest import fixture_bytes
from tests.test_phase2_uploads import make_property


def post_crm(client, property_id, fixture_name, adapter="yardi"):
    return client.post(
        "/api/uploads/crm",
        data={"property_id": property_id, "adapter": adapter},
        files={"file": (fixture_name, fixture_bytes(fixture_name), "text/csv")},
    )


# --- hard rule 4 guard ---


def test_yardi_mapping_is_loudly_fake():
    """Guard for CLAUDE.md hard rule 4: this test must FAIL the moment anyone
    swaps in realistic-looking Yardi column names without going through real
    export samples (and consciously updating this test + is_placeholder)."""
    adapter = YardiAdapter()
    assert adapter.is_placeholder is True
    for source_header in adapter.column_aliases:
        assert "placeholder" in source_header.lower(), source_header
    for status_value in adapter._STATUS_VALUES:
        assert "placeholder" in status_value.lower(), status_value
    assert "PLACEHOLDER" in adapter.label.upper()


# --- adapter normalization ---


def test_normalize_maps_placeholder_statuses():
    adapter = YardiAdapter()
    lead = adapter.normalize(
        {
            "external_lead_id": "L-9",
            "lead_source_raw": "PLACEHOLDER_SOURCE_VALUE_WEBSITE",
            "status": "PLACEHOLDER_STATUS_LEASE",
            "first_contact_date": "2026-06-02",
            "lease_signed_date": "2026-06-15",
        }
    )
    assert lead.status == LeadStatus.LEASE
    assert lead.first_contact_date == date(2026, 6, 2)
    assert lead.lease_signed_date == date(2026, 6, 15)
    assert lead.lead_source_normalized is None


def test_normalize_skips_unknown_status():
    adapter = YardiAdapter()
    result = adapter.normalize(
        {
            "external_lead_id": "L-9",
            "lead_source_raw": "X",
            "status": "SOMETHING_REAL_LOOKING",
            "first_contact_date": "2026-06-02",
        }
    )
    assert "unmapped status" in result.reason


# --- ingestion end-to-end ---


def test_crm_upload_end_to_end(client, db):
    prop = make_property(client)
    resp = post_crm(client, prop["id"], "crm_yardi_placeholder.csv")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["rows_ingested"] == 3
    assert body["rows_skipped"] == 1  # unmapped placeholder status on line 5
    assert body["warnings"] == [PLACEHOLDER_WARNING]
    assert body["date_start"] == "2026-06-01"
    assert body["date_end"] == "2026-06-03"

    leads = {l.external_lead_id: l for l in db.query(CRMLead).all()}
    assert len(leads) == 3
    assert leads["L-1002"].status == LeadStatus.LEASE
    assert leads["L-1002"].lease_signed_date == date(2026, 6, 15)
    assert leads["L-1002"].move_in_date == date(2026, 7, 1)
    assert leads["L-1003"].status == LeadStatus.TOUR
    assert leads["L-1003"].lease_signed_date is None


def test_crm_reupload_upserts_not_duplicates(client, db):
    prop = make_property(client)
    post_crm(client, prop["id"], "crm_yardi_placeholder.csv")
    second = post_crm(client, prop["id"], "crm_yardi_placeholder.csv").json()
    assert second["rows_ingested"] == 0
    assert second["rows_replaced"] == 3  # updated in place
    assert db.query(CRMLead).count() == 3


def test_realistic_export_rejected_with_placeholder_note(client, db):
    prop = make_property(client)
    resp = post_crm(client, prop["id"], "crm_realistic_headers.csv")
    assert resp.status_code == 422
    assert "PLACEHOLDER" in resp.json()["detail"]

    upload = db.query(Upload).one()
    assert upload.status == UploadStatus.FAILED
    assert "PLACEHOLDER" in upload.error_message


def test_unknown_adapter_rejected(client):
    prop = make_property(client)
    resp = post_crm(client, prop["id"], "crm_yardi_placeholder.csv", adapter="salesforce")
    assert resp.status_code == 422
    assert "yardi" in resp.json()["detail"]


def test_adapter_registry():
    assert set(ADAPTERS) == {"yardi"}
