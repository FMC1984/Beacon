"""Phase 16E: AEO Readiness report. An explainable, deterministic score; a
question-by-page heatmap driven by term rules (never vector similarity); a
citation-readiness component that never promises a citation; and a
structured-data section that reports its not-configured state rather than
fabricating results."""

from datetime import date, datetime, timezone

import pytest

from app.models import Property, PropertyContent
from app.services.reporting import DataState
from app.services.reporting_aeo import (
    CITATION_DISCLAIMER,
    COMPONENT_WEIGHTS,
    build_aeo_report,
)

TODAY = date(2026, 7, 5)

# Rich homepage that answers several multifamily renter questions with concept
# and detail terms, plus the property name and city for local + citation signals.
RICH_HOMEPAGE = (
    "Solara Flats in Tempe, Arizona offers studio, one bedroom, and two bedroom "
    "floor plans starting at $1,450 per month. Apply online through our resident "
    "portal. Pet-friendly with a dog park; a pet fee and breed restrictions apply. "
    "Assigned covered parking is available. Submit a maintenance request online any "
    "time. Amenities include a resort-style pool and a 24-hour fitness center."
)


def _prop(db, name="Solara Flats", city="Tempe", state="AZ", ptype="multifamily_apartment"):
    p = Property(
        name=name, slug=name.lower().replace(" ", "-"), city=city, state=state,
        property_type=ptype, website_url="https://solaraflats.com",
    )
    db.add(p)
    db.commit()
    return p


_DEFAULT_UPDATED = object()  # sentinel: "use the default date"


def _content(db, pid, page, body, updated=_DEFAULT_UPDATED):
    # updated=None means explicitly no date; the sentinel means the default.
    updated_at = datetime(2026, 6, 15, tzinfo=timezone.utc) if updated is _DEFAULT_UPDATED else updated
    db.add(PropertyContent(
        property_id=pid, page=page, title=page.title(), body=body,
        updated_at=updated_at,
    ))
    db.commit()


@pytest.fixture()
def aeo_property(db):
    p = _prop(db)
    _content(db, p.id, "homepage", RICH_HOMEPAGE)
    _content(db, p.id, "faq", "Frequently asked questions about applying and pet policy at Solara Flats.")
    return p


# --- no content --------------------------------------------------------------


def test_no_content_is_honest(db):
    p = _prop(db, "Empty Flats")
    r = build_aeo_report(db, p.id, today=TODAY)
    assert r["has_content"] is False
    assert "no website content" in r["message"].lower()
    # Even without content, structured data reports its honest state.
    assert r["structured_data"]["state"] == DataState.NOT_CONFIGURED.value


# --- score: explainable, weighted, no opaque number --------------------------


def test_score_is_weighted_average_of_components(db, aeo_property):
    r = build_aeo_report(db, aeo_property.id, today=TODAY)
    score = r["score"]
    assert 0 <= score["value"] <= 100
    assert score["grade"] in list("ABCDF")
    scored = [c for c in score["components"] if not c["excluded"]]
    total_w = sum(c["weight"] for c in scored)
    expected = round(sum(c["raw_value"] * c["weight"] for c in scored) / total_w)
    assert score["value"] == expected


def test_every_component_is_explainable(db, aeo_property):
    r = build_aeo_report(db, aeo_property.id, today=TODAY)
    for c in r["score"]["components"]:
        assert c["key"] in COMPONENT_WEIGHTS
        assert c["weight"] == COMPONENT_WEIGHTS[c["key"]]
        assert c["rule"] and c["explanation"]
        # A scored component publishes a raw value; an excluded one does not.
        if c["excluded"]:
            assert c["raw_value"] is None and c["excluded_reason"]
        else:
            assert c["raw_value"] is not None


def test_components_with_no_signal_are_excluded_not_zero(db):
    # Content with no update dates and no dated text -> freshness excluded.
    p = _prop(db, "Dateless Flats")
    _content(db, p.id, "homepage", "Solara living in Tempe. Apply online.", updated=None)
    r = build_aeo_report(db, p.id, today=TODAY)
    comps = {c["key"]: c for c in r["score"]["components"]}
    assert comps["freshness"]["excluded"] is True
    assert comps["freshness"]["raw_value"] is None
    assert "freshness" in r["score"]["excluded_components"]
    # The excluded component's weight is dropped, not counted as a zero.
    scored = [c for c in r["score"]["components"] if not c["excluded"]]
    assert all(c["raw_value"] is not None for c in scored)


def test_score_is_deterministic(db, aeo_property):
    a = build_aeo_report(db, aeo_property.id, today=TODAY)
    b = build_aeo_report(db, aeo_property.id, today=TODAY)
    assert a["score"] == b["score"]


# --- heatmap: deterministic cell rules ---------------------------------------


def test_heatmap_cell_states_follow_term_rules(db, aeo_property):
    r = build_aeo_report(db, aeo_property.id, today=TODAY)
    hm = r["heatmap"]
    assert "homepage" in hm["pages"] and "faq" in hm["pages"]

    # The rich homepage answers at least one question fully (concept + detail),
    # and a fully-answered cell always carries the terms it matched on.
    homepage_cells = [
        c for row in hm["rows"] for c in row["cells"] if c["page"] == "homepage"
    ]
    fully = [c for c in homepage_cells if c["state"] == "fully_answered"]
    assert fully, "rich homepage should fully answer at least one question"
    assert all(c["matched_terms"] for c in fully)

    # Every cell has a valid deterministic state and inspectable matched terms.
    for row in hm["rows"]:
        for c in row["cells"]:
            assert c["state"] in (
                "fully_answered", "partially_answered", "mentioned_only", "missing"
            )
            assert isinstance(c["matched_terms"], list)
            if c["state"] == "missing":
                assert c["matched_terms"] == []


def test_heatmap_missing_when_no_terms(db):
    p = _prop(db, "Sparse Flats")
    # Content about the pool only; a parking question should be missing.
    _content(db, p.id, "homepage", "A lovely community with a resort-style pool.")
    r = build_aeo_report(db, p.id, today=TODAY)
    hm = r["heatmap"]
    parking = next((row for row in hm["rows"] if "parking" in row["question"].lower()), None)
    if parking:
        assert all(c["state"] == "missing" for c in parking["cells"])


# --- citation readiness ------------------------------------------------------


def test_citation_readiness_has_signals_and_disclaimer(db, aeo_property):
    r = build_aeo_report(db, aeo_property.id, today=TODAY)
    cr = r["citation_readiness"]
    assert cr["disclaimer"] == CITATION_DISCLAIMER
    assert "does not guarantee" in cr["disclaimer"]
    assert "—" not in cr["disclaimer"]
    homepage = next(p for p in cr["pages"] if p["page"] == "homepage")
    sig = homepage["signals"]
    assert set(sig) == {
        "clear_heading", "specific_answer_present", "named_property",
        "updated_date", "crawlable_text",
    }
    assert sig["named_property"] is True  # "Solara Flats" appears in the body
    assert sig["updated_date"] is True  # updated_at was set


def test_citation_disclaimer_present_in_report_root(db, aeo_property):
    r = build_aeo_report(db, aeo_property.id, today=TODAY)
    assert r["citation_disclaimer"] == CITATION_DISCLAIMER


# --- structured data: not fabricated -----------------------------------------


def test_structured_data_not_fabricated(db, aeo_property):
    sd = build_aeo_report(db, aeo_property.id, today=TODAY)["structured_data"]
    assert sd["enabled"] is False
    assert sd["state"] == DataState.NOT_CONFIGURED.value
    assert sd["valid_items"] is None and sd["invalid_items"] is None
    assert sd["schema_types"] == []


# --- endpoint + isolation + CSV ----------------------------------------------


def test_aeo_endpoint_and_csv_client_safe(client, db, aeo_property):
    r = client.get(f"/api/reports/aeo?property_id={aeo_property.id}")
    assert r.status_code == 200
    assert r.json()["has_content"] is True

    csv = client.get(f"/api/reports/aeo/export.csv?property_id={aeo_property.id}")
    assert csv.status_code == 200
    text = csv.text
    assert "AEO Readiness score" in text
    assert CITATION_DISCLAIMER in text
    for forbidden in ["chunk_id", "vector", "similarity", "embedding", "latency"]:
        assert forbidden not in text.lower()


def test_aeo_portfolio_scope_requires_property(db):
    assert build_aeo_report(db, None)["scope_required"] is True


def test_aeo_endpoint_unknown_property_404s(client):
    assert client.get("/api/reports/aeo?property_id=999").status_code == 404


def test_aeo_scope_isolation(client, db, aeo_property):
    other = _prop(db, "Separate Flats")  # no content
    r = client.get(f"/api/reports/aeo?property_id={other.id}").json()
    assert r["has_content"] is False


def test_meta_marks_aeo_available(client):
    tabs = {t["key"]: t for t in client.get("/api/reports/meta").json()["tabs"]}
    assert tabs["aeo"]["status"] == "available"
