"""Data export: ZIP bundle contents, property vs portfolio scope, and the
AI-traffic disclosure carried in the manifest."""

import io
import zipfile

from tests.test_phase2_uploads import make_property, post_upload

from app.constants import AI_TRAFFIC_DISCLOSURE


def _open_zip(resp):
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/zip"
    return zipfile.ZipFile(io.BytesIO(resp.content))


def test_portfolio_export_has_all_files_and_disclosure(client):
    prop = make_property(client, "Solara Flats")
    post_upload(client, "ga4", prop["id"], "ga4_traffic_with_date.csv")

    resp = client.get("/api/export")
    zf = _open_zip(resp)
    names = set(zf.namelist())
    assert {
        "properties.csv",
        "ga4_sessions_daily.csv",
        "gsc_performance_daily.csv",
        "gbp_metrics_daily.csv",
        "paid_media_daily.csv",
        "crm_leads.csv",
        "manifest.txt",
    } <= names

    manifest = zf.read("manifest.txt").decode()
    assert AI_TRAFFIC_DISCLOSURE in manifest
    assert "portfolio" in manifest

    ga4 = zf.read("ga4_sessions_daily.csv").decode()
    assert "property" in ga4.splitlines()[0]  # property column leads
    assert "Solara Flats" in ga4
    assert "is_ai_referral" in ga4


def test_property_export_scoped_to_one_property(client):
    a = make_property(client, "Solara Flats")
    make_property(client, "The Marlowe")
    post_upload(client, "ga4", a["id"], "ga4_traffic_with_date.csv")

    resp = client.get(f"/api/export?property_id={a['id']}")
    zf = _open_zip(resp)

    props = zf.read("properties.csv").decode()
    assert "Solara Flats" in props
    assert "The Marlowe" not in props

    manifest = zf.read("manifest.txt").decode()
    assert "Solara Flats" in manifest
    filename = resp.headers["content-disposition"]
    assert "solara-flats" in filename


def test_export_unknown_property_404(client):
    resp = client.get("/api/export?property_id=99999")
    assert resp.status_code == 404


def test_empty_portfolio_export_still_valid_zip(client):
    resp = client.get("/api/export")
    zf = _open_zip(resp)
    # Header row present, zero data rows.
    assert zf.read("ga4_sessions_daily.csv").decode().count("\n") == 1
    assert "0 row(s)" in zf.read("manifest.txt").decode()
