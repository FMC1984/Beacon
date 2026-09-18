"""AI readability v1: raw HTML, robots.txt and structured data, with no real fetches."""

from datetime import datetime, timedelta

import httpx

from app.models import AIReadabilityCheck, Property
from app.services.observatory.demo_seed import build_sample_portfolio, remove_sample_portfolio
from app.services.observatory.readability import analyze_html, build_findings, check_due, readability_report, run_check

NOW = datetime(2026, 9, 10, 12, 0)

HOME = """<html><head><title>Willow Creek</title>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"ApartmentComplex","name":"Willow Creek"}</script>
<script src="app.js"></script></head>
<body><nav><a href="/floorplans">Floor Plans</a><a href="/amenities">Amenities</a><a href="https://other.example/x">Off</a></nav>
<main><h1>Willow Creek Apartments</h1><p>Pet friendly community with a resort-style pool and fitness center, located minutes from downtown.</p>
<p>Call (303) 555-0100 or schedule a tour.</p></main></body></html>"""
FLOORPLANS = "<html><body><h2>Floor plans</h2><p>Studio, 1 bedroom and 2 bedroom homes. Check availability online.</p></body></html>"
JS_ONLY = "<html><head>" + "<script src='a.js'></script>" * 6 + "</head><body><div id='app'></div></body></html>"
ROBOTS = "User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n"


def _client(pages: dict[str, tuple[int, str, str]]):
    def handler(request: httpx.Request) -> httpx.Response:
        status, ctype, body = pages.get(str(request.url), (404, "text/html", "missing"))
        return httpx.Response(status, headers={"content-type": ctype}, text=body)

    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def _prop(db, **kw):
    p = Property(name="Willow Creek", slug="willow-creek", city="Denver", state="CO", website_url="https://willowcreek.example/", **kw)
    db.add(p)
    db.commit()
    return p


def test_analyze_html_finds_categories_and_structured_data_without_scripts():
    a = analyze_html(HOME)
    assert a["jsonld_types"] == ["ApartmentComplex"] and a["scripts"] == 2
    assert {"pets", "amenities", "neighborhood", "contact"} <= set(a["found"])
    assert "pricing" not in a["found"] and "app.js" not in a["found"].get("contact", "")
    assert "/floorplans" in a["links"]


def test_run_check_reads_linked_pages_robots_and_reports_honestly(db):
    p = _prop(db)
    client = _client({
        "https://willowcreek.example/": (200, "text/html", HOME),
        "https://willowcreek.example/floorplans": (200, "text/html", FLOORPLANS),
        "https://willowcreek.example/amenities": (500, "text/html", "boom"),
        "https://willowcreek.example/robots.txt": (200, "text/plain", ROBOTS),
    })
    row = run_check(db, p.id, now=NOW, client=client)
    assert row.status == "ok"
    cats = row.categories
    assert cats["floor_plans"]["present"]  # the nav link text "Floor Plans" is visible on the homepage
    assert cats["availability"]["present"] and cats["availability"]["page"].endswith("/floorplans")
    assert not cats["pricing"]["present"]
    assert row.robots["agents"]["GPTBot"] == "disallowed" and row.robots["agents"]["ClaudeBot"] == "allowed"
    assert row.structured_data == ["ApartmentComplex"]
    sev = {f["category"]: f["severity"] for f in row.findings}
    assert sev["pricing"] == "critical" and sev["robots"] == "critical" and "fees" in sev
    amen = next(pg for pg in row.pages if pg["url"].endswith("/amenities"))
    assert amen["error"] == "HTTP 500" and amen["chars"] is None
    text = " ".join(f["text"] for f in row.findings)
    assert "may be rendered by a script or not published" in text and "hidden" not in text.lower()
    rep = readability_report(db, p.id)
    assert rep["checked"] and rep["summary"]["present"] == rep["summary"]["total"] - 2  # pricing, fees
    assert "no JavaScript run" in rep["note"]


def test_script_only_homepage_is_flagged_as_likely_rendered(db):
    p = _prop(db)
    client = _client({"https://willowcreek.example/": (200, "text/html", JS_ONLY),
                      "https://willowcreek.example/robots.txt": (404, "text/plain", "")})
    row = run_check(db, p.id, now=NOW, client=client)
    assert row.status == "ok" and row.robots["present"] is False and row.robots["agents"]["GPTBot"] == "allowed"
    assert any(f["category"] == "rendering" for f in row.findings)
    assert all(not c["present"] for c in row.categories.values())


def test_unreachable_homepage_and_missing_url_are_errors_not_findings_about_content(db):
    p = _prop(db)
    client = _client({"https://willowcreek.example/robots.txt": (200, "text/plain", "User-agent: *\nAllow: /\n")})
    row = run_check(db, p.id, now=NOW, client=client)
    assert row.status == "error" and "HTTP 404" in row.error
    assert not any(f["category"] in ("pricing", "pets") for f in row.findings)
    bare = Property(name="No Site", slug="no-site")
    db.add(bare)
    db.commit()
    assert run_check(db, bare.id, now=NOW).error.startswith("No website URL")
    assert readability_report(db, bare.id)["checked"] is True


def test_sample_properties_are_never_fetched_and_seeded_checks_are_removable(db, monkeypatch):
    import app.services.observatory.readability as mod

    monkeypatch.setattr(mod.httpx, "Client", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network call")))
    build_sample_portfolio(db, now=NOW, weeks=4)
    maple = db.query(Property).filter_by(name="Maple Ridge Flats").one()
    rep = readability_report(db, maple.id)
    assert rep["checked"] and rep["is_sample"] and rep["summary"]["total"] == 8
    row = run_check(db, maple.id, now=NOW)
    assert row.status == "error" and "Sample" in row.error
    assert check_due(db, now=NOW) == {"checked": 0}
    remove_sample_portfolio(db)
    assert db.query(AIReadabilityCheck).filter_by(source="sample").count() == 0


def test_check_due_respects_the_weekly_interval(db, monkeypatch):
    import app.services.observatory.readability as mod

    calls = []
    monkeypatch.setattr(mod, "run_check", lambda db_, pid, now=None: calls.append(pid))
    p = _prop(db)
    assert check_due(db, now=NOW) == {"checked": 1}
    db.add(AIReadabilityCheck(property_id=p.id, checked_at=NOW - timedelta(days=2), site_url=p.website_url, status="ok"))
    db.commit()
    assert check_due(db, now=NOW) == {"checked": 0}
    assert check_due(db, now=NOW + timedelta(days=8)) == {"checked": 1}


def test_housing_authority_is_checked_on_its_own_questions(db):
    ha = Property(name="County Housing", slug="county-housing", property_type="housing_authority",
                  website_url="https://countyhousing.example/")
    db.add(ha)
    db.commit()
    html = "<html><body><p>Check your eligibility and income limits, then apply to the waitlist for our programs.</p><p>Call (303) 555-0100.</p></body></html>"
    client = _client({"https://countyhousing.example/": (200, "text/html", html),
                      "https://countyhousing.example/robots.txt": (404, "text/plain", "")})
    row = run_check(db, ha.id, now=NOW, client=client)
    assert set(row.categories) == {"eligibility", "apply", "programs", "developments", "neighborhood", "contact"}
    assert row.categories["eligibility"]["present"] and row.categories["apply"]["present"]
    assert not any(f["category"] in ("pets", "floor_plans", "pricing") for f in row.findings)
    assert readability_report(db, ha.id)["summary"]["total"] == 6


def test_endpoints(client, db):
    p = _prop(db)
    r = client.get("/api/ai-observatory/readability", params={"property_id": p.id})
    assert r.status_code == 200 and r.json()["checked"] is False
    q = client.post("/api/ai-observatory/readability/check", params={"property_id": p.id})
    assert q.status_code == 200 and q.json()["created"] is True
    assert client.post("/api/ai-observatory/readability/check", params={"property_id": p.id}).json()["created"] is False
    assert client.get("/api/ai-observatory/readability", params={"property_id": 999999}).status_code == 404
