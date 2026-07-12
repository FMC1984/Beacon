"""Company CRUD, property<->company assignment, and company-scoped dashboard
and export."""

import io
import zipfile

from tests.test_phase2_uploads import make_property, post_upload


def make_company(client, name="Skyline Residential"):
    resp = client.post("/api/companies", json={"name": name})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_company_crud_and_counts(client):
    co = make_company(client, "Skyline Residential")
    assert co["slug"] == "skyline-residential"
    assert co["property_count"] == 0

    # Duplicate name rejected.
    assert client.post("/api/companies", json={"name": "Skyline Residential"}).status_code == 409

    # Assign a property; count reflects it.
    prop = make_property(client, "Willow Creek")
    client.patch(f"/api/properties/{prop['id']}", json={"company_id": co["id"]})
    listed = client.get("/api/companies").json()
    assert listed[0]["property_count"] == 1

    # Rename.
    renamed = client.patch(f"/api/companies/{co['id']}", json={"name": "Skyline Group"})
    assert renamed.status_code == 200
    assert renamed.json()["slug"] == "skyline-group"


def test_create_property_with_company(client):
    co = make_company(client)
    resp = client.post(
        "/api/properties",
        json={"name": "Cedar Point", "company_id": co["id"]},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["company_id"] == co["id"]


def test_property_rejects_unknown_company(client):
    resp = client.post(
        "/api/properties", json={"name": "Ghost Prop", "company_id": 9999}
    )
    assert resp.status_code == 422


def test_delete_company_unassigns_properties_keeps_data(client, db):
    co = make_company(client)
    prop = make_property(client, "Marlowe")
    client.patch(f"/api/properties/{prop['id']}", json={"company_id": co["id"]})

    resp = client.delete(f"/api/companies/{co['id']}")
    assert resp.status_code == 200
    assert resp.json()["unassigned"] == 1

    # Property still exists, now unassigned.
    after = client.get(f"/api/properties/{prop['id']}").json()
    assert after["company_id"] is None
    assert client.get(f"/api/companies/{co['id']}").status_code in (404, 405)


def test_unassign_via_patch_null(client):
    co = make_company(client)
    prop = make_property(client, "Driftwood")
    client.patch(f"/api/properties/{prop['id']}", json={"company_id": co["id"]})
    # Explicit null unassigns.
    resp = client.patch(f"/api/properties/{prop['id']}", json={"company_id": None})
    assert resp.json()["company_id"] is None


def test_dashboard_scoped_to_company_aggregates_its_properties(client):
    co = make_company(client)
    a = make_property(client, "Solara Flats")
    b = make_property(client, "Outsider Property")  # NOT in the company
    client.patch(f"/api/properties/{a['id']}", json={"company_id": co["id"]})
    post_upload(client, "ga4", a["id"], "ga4_traffic_with_date.csv")
    post_upload(client, "ga4", b["id"], "ga4_traffic_with_date.csv")

    company_dash = client.get(f"/api/dashboard?company_id={co['id']}&days=365").json()
    prop_dash = client.get(f"/api/dashboard?property_id={a['id']}&days=365").json()
    portfolio = client.get("/api/dashboard?days=365").json()

    # Company scope has data and, since only one property is in it, matches that
    # property; the full portfolio (two properties) has strictly more sessions.
    assert company_dash["ga4"] is not None
    assert company_dash["ga4"]["sessions"] == prop_dash["ga4"]["sessions"]
    assert portfolio["ga4"]["sessions"] > company_dash["ga4"]["sessions"]


def test_dashboard_company_with_no_properties_is_empty(client):
    co = make_company(client)
    dash = client.get(f"/api/dashboard?company_id={co['id']}").json()
    assert dash["ga4"] is None and dash["crm"] is None


def test_dashboard_unknown_company_404(client):
    assert client.get("/api/dashboard?company_id=9999").status_code == 404


def test_export_scoped_to_company(client):
    co = make_company(client, "Beacon Holdings")
    a = make_property(client, "Solara Flats")
    make_property(client, "Not In Company")
    client.patch(f"/api/properties/{a['id']}", json={"company_id": co["id"]})
    post_upload(client, "ga4", a["id"], "ga4_traffic_with_date.csv")

    resp = client.get(f"/api/export?company_id={co['id']}")
    assert resp.status_code == 200
    assert "beacon-holdings" in resp.headers["content-disposition"]
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    props = zf.read("properties.csv").decode()
    assert "Solara Flats" in props
    assert "Not In Company" not in props
    assert "company - Beacon Holdings" in zf.read("manifest.txt").decode()


def test_export_unknown_company_404(client):
    assert client.get("/api/export?company_id=9999").status_code == 404
