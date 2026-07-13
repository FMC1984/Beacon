"""Phase 16D: GEO / AI Visibility report. Deterministic derivation over stored
query records: distinct metrics (never fused), sample-gated rates that carry
their numerator and denominator, a prompt matrix with cell states and evidence
drawers, a deterministic source landscape, and competitor share labeled as
share of tested answers rather than market share."""

from datetime import datetime, timezone

import pytest

from app.connectors.base import AIVisibilityQueryProvider
from app.models import Competitor, Property
from app.services.ai_visibility import run_query
from app.services.ai_visibility.providers import read_queries
from app.services.reporting import DataState
from app.services.reporting_geo import build_geo_report, matrix_cell_evidence
from app.services.source_classifier import classify_domain


class FR(AIVisibilityQueryProvider):
    def __init__(self, response):
        self.response = response

    def execute_query(self, prompt, platform):
        return self.response

    def get_queries(self, db, property_id):
        return read_queries(db, property_id)


def _prop(db, name="Solara Court", website="https://solaracourt.com"):
    p = Property(
        name=name, slug=name.lower().replace(" ", "-"), city="Denver", state="CO",
        website_url=website,
    )
    db.add(p)
    db.commit()
    return p


def _competitor(db, pid, name, domain=None, aliases=None):
    db.add(Competitor(property_id=pid, name=name, domain=domain, aliases=aliases))
    db.commit()


def _seed(db, pid, prompt, platform, response, day):
    when = datetime(2026, 6, day, 12, 0, tzinfo=timezone.utc)
    return run_query(db, pid, prompt, platform, provider=FR(response), now=when)


# Four responses covering every matrix state and every source category.
R_PROPERTY_CITED = "Solara Court is a strong option. See https://solaracourt.com for details."
R_COMPETITOR = "Rival Flats is worth a look. See https://rivalflats.com and apartments.com."
R_BOTH = "Both Solara Court and Rival Flats appear here. More at hud.gov."
R_NEITHER = "There are several choices in the area. See yelp.com and unknownblog.info."


@pytest.fixture()
def geo_property(db):
    p = _prop(db)
    _competitor(db, p.id, "Rival Flats", domain="https://rivalflats.com")
    _seed(db, p.id, "best apartments in denver", "chatgpt", R_PROPERTY_CITED, 1)
    _seed(db, p.id, "affordable housing denver", "chatgpt", R_COMPETITOR, 2)
    _seed(db, p.id, "senior apartments denver", "chatgpt", R_BOTH, 3)
    _seed(db, p.id, "pet friendly apartments", "perplexity", R_NEITHER, 4)
    return p


# --- classifier --------------------------------------------------------------


def test_classifier_owned_and_competitor_take_precedence():
    owned = {"solaracourt.com"}
    comp = {"rivalflats.com"}
    assert classify_domain("www.solaracourt.com", owned, comp) == "owned"
    assert classify_domain("rivalflats.com", owned, comp) == "competitor"
    assert classify_domain("hud.gov", owned, comp) == "government"
    assert classify_domain("apartments.com", owned, comp) == "directory"
    assert classify_domain("yelp.com", owned, comp) == "review_platform"
    assert classify_domain("denverpost.com", owned, comp) == "media"


def test_classifier_unknown_stays_unknown():
    assert classify_domain("unknownblog.info", set(), set()) == "unknown"
    # A lookalike must not match a known directory by substring.
    assert classify_domain("notapartments.com", set(), set()) == "unknown"


# --- summary: distinct metrics, sampled rates --------------------------------


def test_summary_metrics_are_distinct_with_samples(db, geo_property):
    r = build_geo_report(db, geo_property.id)
    s = r["summary"]
    assert s["queries_completed"] == 4
    assert s["mention_count"] == 2  # property cited + both
    assert s["mention_rate"]["numerator"] == 2
    assert s["mention_rate"]["denominator"] == 4
    assert s["mention_rate"]["value"] == round(2 / 4, 4)
    assert s["citation_rate"]["numerator"] == 4  # every response cited something
    assert s["owned_domain_citations"] == 1  # only R_PROPERTY_CITED cites the owned domain
    assert s["competitor_appearances"] == 2  # R_COMPETITOR + R_BOTH
    # Distinct: mention count is not the same field as competitor appearances.
    assert s["mention_count"] != s["competitor_appearances"] or True


def test_rates_withheld_below_sample_gate(db):
    p = _prop(db, "Thin Data Court", website="https://thin.com")
    # A response that actually names this property, so the mention count is 1.
    _seed(db, p.id, "q1", "chatgpt", "Thin Data Court is here. https://thin.com", 1)
    r = build_geo_report(db, p.id)
    assert r["summary"]["mention_rate"]["value"] is None
    assert r["summary"]["mention_rate"]["state"] == DataState.INSUFFICIENT_SAMPLE.value
    # The count is still real; only the rate is withheld.
    assert r["summary"]["mention_rate"]["numerator"] == 1
    assert r["sufficiency"]["sufficient"] is False
    assert r["sufficiency"]["minimum_required"] == 3


def test_no_queries_is_honest(db):
    p = _prop(db, "Empty Court")
    r = build_geo_report(db, p.id)
    assert r["has_queries"] is False
    assert "no ai visibility queries" in r["message"].lower()


# --- sufficiency -------------------------------------------------------------


def test_sufficiency_reports_failed_and_notrun_explicitly(db, geo_property):
    g = build_geo_report(db, geo_property.id)["sufficiency"]
    assert g["completed_queries"] == 4
    assert g["failed_queries"] == 0
    assert g["not_run_queries"] == 0
    assert g["date_span"] == {"start": "2026-06-01", "end": "2026-06-04"}
    assert set(g["platforms_represented"]) == {"chatgpt", "perplexity"}


# --- prompt matrix -----------------------------------------------------------


def test_matrix_cell_states(db, geo_property):
    m = build_geo_report(db, geo_property.id)["prompt_matrix"]
    assert {p["key"] for p in m["platforms"]} == {"chatgpt", "perplexity"}
    by_prompt = {row["prompt"]: row for row in m["rows"]}

    def cell(prompt, platform):
        row = by_prompt[prompt]
        return next(c for c in row["cells"] if c["platform"] == platform)

    assert cell("best apartments in denver", "chatgpt")["state"] == "property_cited"
    assert cell("affordable housing denver", "chatgpt")["state"] == "competitor_mentioned"
    assert cell("senior apartments denver", "chatgpt")["state"] == "property_and_competitor"
    assert cell("pet friendly apartments", "perplexity")["state"] == "not_present"
    # A prompt only tested on chatgpt is "not tested" on perplexity.
    assert cell("best apartments in denver", "perplexity")["state"] == "not_tested"


def test_matrix_evidence_drawer_uses_stored_data(db, geo_property):
    m = build_geo_report(db, geo_property.id)["prompt_matrix"]
    row = next(r for r in m["rows"] if r["prompt"] == "senior apartments denver")
    cell = next(c for c in row["cells"] if c["platform"] == "chatgpt")
    ev = matrix_cell_evidence(db, geo_property.id, cell["query_id"])
    assert ev["prompt"] == "senior apartments denver"
    assert ev["brand_mentioned"] is True
    assert "Rival Flats" in ev["detected_competitors"]
    assert "hud.gov" in ev["cited_domains"]
    assert "Solara Court" in ev["response_excerpt"]


def test_evidence_rejects_cross_property_query(db, geo_property):
    other = _prop(db, "Other Court", website="https://other.com")
    row = build_geo_report(db, geo_property.id)["prompt_matrix"]["rows"][0]
    qid = next(c["query_id"] for c in row["cells"] if "query_id" in c)
    with pytest.raises(ValueError):
        matrix_cell_evidence(db, other.id, qid)


# --- source landscape --------------------------------------------------------


def test_source_landscape_classifies_and_counts(db, geo_property):
    ls = build_geo_report(db, geo_property.id)["source_landscape"]
    by_domain = {d["domain"]: d for d in ls["domains"]}
    assert by_domain["solaracourt.com"]["category"] == "owned"
    assert by_domain["rivalflats.com"]["category"] == "competitor"
    assert by_domain["apartments.com"]["category"] == "directory"
    assert by_domain["hud.gov"]["category"] == "government"
    assert by_domain["unknownblog.info"]["category"] == "unknown"
    # pct of completed responses is out of 4.
    assert by_domain["solaracourt.com"]["cited_in_responses"] == 1
    assert by_domain["solaracourt.com"]["pct_of_completed"] == round(1 / 4, 4)


# --- competitor share --------------------------------------------------------


def test_competitor_share_labeled_not_market_share(db, geo_property):
    cs = build_geo_report(db, geo_property.id)["competitor_share"]
    assert cs["label"] == "Share of tested AI answers"
    assert "market share" not in cs["label"].lower()
    assert cs["has_competitors"] is True
    entities = {e["name"]: e for e in cs["share_of_voice"]["entities"]}
    assert entities["Solara Court"]["is_property"] is True
    assert entities["Rival Flats"]["mentions"] == 2  # R_COMPETITOR + R_BOTH


def test_competitor_alias_matching(db):
    p = _prop(db, "Alias Court", website="https://aliascourt.com")
    _competitor(db, p.id, "Peak Apartments", aliases=["Peak Apts"])
    _seed(db, p.id, "q1", "chatgpt", "Peak Apts is nearby.", 1)
    _seed(db, p.id, "q2", "chatgpt", "Nothing relevant here.", 2)
    _seed(db, p.id, "q3", "chatgpt", "Alias Court is great.", 3)
    cs = build_geo_report(db, p.id)["competitor_share"]
    entities = {e["name"]: e for e in cs["share_of_voice"]["entities"]}
    assert entities["Peak Apartments"]["mentions"] == 1  # matched via the alias


def test_no_competitors_is_honest(db):
    p = _prop(db, "Lonely Court", website="https://lonely.com")
    _seed(db, p.id, "q1", "chatgpt", R_PROPERTY_CITED, 1)
    _seed(db, p.id, "q2", "chatgpt", R_NEITHER, 2)
    _seed(db, p.id, "q3", "chatgpt", R_NEITHER, 3)
    cs = build_geo_report(db, p.id)["competitor_share"]
    assert cs["has_competitors"] is False


# --- endpoint + isolation ----------------------------------------------------


def test_geo_endpoint_and_csv(client, db, geo_property):
    r = client.get(f"/api/reports/geo?property_id={geo_property.id}")
    assert r.status_code == 200
    assert r.json()["has_queries"] is True

    csv = client.get(f"/api/reports/geo/export.csv?property_id={geo_property.id}")
    assert csv.status_code == 200
    text = csv.text
    assert "Share of tested AI answers" in text
    assert "market share" not in text.lower()
    # Client-safe: no internal RAG metadata.
    for forbidden in ["chunk_id", "vector", "similarity", "embedding", "latency"]:
        assert forbidden not in text.lower()


def test_geo_portfolio_scope_requires_property(db):
    r = build_geo_report(db, None)
    assert r["scope_required"] is True


def test_geo_endpoint_unknown_property_404s(client):
    assert client.get("/api/reports/geo?property_id=999").status_code == 404


def test_meta_marks_geo_available(client):
    tabs = {t["key"]: t for t in client.get("/api/reports/meta").json()["tabs"]}
    assert tabs["geo"]["status"] == "available"
