"""URL content-fetch: HTML extraction, error handling, and the
POST /api/content/{property_id}/{page}/fetch endpoint. All network calls are
mocked so the suite runs deterministically offline."""

import httpx
import pytest

from app.models import PropertyContent
from app.services.content_fetch import ContentFetchError, fetch_page_content
from tests.test_phase2_uploads import make_property

SAMPLE_HTML = """
<html>
<head><title>Solara Flats - Apartments in Tempe</title></head>
<body>
  <nav>Home Amenities Contact</nav>
  <header>Solara Flats</header>
  <main>
    <h1>Welcome to Solara Flats</h1>
    <p>Resort-style pool and 24-hour fitness center in Tempe, AZ.</p>
    <script>console.log("tracking");</script>
  </main>
  <footer>Copyright 2026</footer>
</body>
</html>
"""


class FakeResponse:
    def __init__(self, text, status_code=200, content_type="text/html"):
        self.text = text
        self.status_code = status_code
        self.headers = {"content-type": content_type}


def test_fetch_extracts_title_and_strips_boilerplate(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(SAMPLE_HTML))
    result = fetch_page_content("https://example.com")
    assert result["title"] == "Solara Flats - Apartments in Tempe"
    assert "Resort-style pool" in result["body"]
    assert "console.log" not in result["body"]
    assert "Copyright 2026" not in result["body"]  # footer stripped
    assert "Home Amenities Contact" not in result["body"]  # nav stripped
    assert result["char_count"] > 0
    assert result["truncated"] is False


def test_fetch_rejects_non_http_scheme():
    with pytest.raises(ContentFetchError, match="http"):
        fetch_page_content("ftp://example.com")


def test_fetch_rejects_empty_url():
    with pytest.raises(ContentFetchError):
        fetch_page_content("")


def test_fetch_surfaces_http_error(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse("", status_code=403))
    with pytest.raises(ContentFetchError, match="403"):
        fetch_page_content("https://example.com")


def test_fetch_rejects_non_html_content_type(monkeypatch):
    monkeypatch.setattr(
        httpx, "get", lambda *a, **k: FakeResponse("{}", content_type="application/json")
    )
    with pytest.raises(ContentFetchError, match="HTML"):
        fetch_page_content("https://example.com/api")


def test_fetch_timeout_readable_error(monkeypatch):
    def raise_timeout(*a, **k):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx, "get", raise_timeout)
    with pytest.raises(ContentFetchError, match="Timed out"):
        fetch_page_content("https://example.com")


def test_fetch_truncates_long_pages(monkeypatch):
    long_html = f"<html><body><main>{'word ' * 10000}</main></body></html>"
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(long_html))
    result = fetch_page_content("https://example.com")
    assert result["truncated"] is True
    assert len(result["body"]) <= 20_000


# --- endpoint ---


def test_fetch_endpoint_saves_content(client, db, monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(SAMPLE_HTML))
    prop = make_property(client, "Fetch Property")
    resp = client.post(
        f"/api/content/{prop['id']}/homepage/fetch",
        json={"url": "https://example.com", "mapped_keyword": "apartments in tempe"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["page"]["title"] == "Solara Flats - Apartments in Tempe"
    assert body["page"]["source_url"] == "https://example.com"
    assert body["page"]["mapped_keyword"] == "apartments in tempe"
    assert body["char_count"] > 0

    row = db.query(PropertyContent).filter_by(property_id=prop["id"]).one()
    assert row.page == "homepage"
    assert "Resort-style pool" in row.body


def test_fetch_endpoint_invalid_page_rejected(client, monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(SAMPLE_HTML))
    prop = make_property(client, "Bad Page Fetch")
    resp = client.post(
        f"/api/content/{prop['id']}/pricing/fetch", json={"url": "https://example.com"}
    )
    assert resp.status_code == 422
    assert "page must be one of" in resp.json()["detail"]


def test_fetch_endpoint_surfaces_fetch_failure(client, monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse("", status_code=404))
    prop = make_property(client, "Failed Fetch")
    resp = client.post(
        f"/api/content/{prop['id']}/homepage/fetch", json={"url": "https://example.com/gone"}
    )
    assert resp.status_code == 422
    assert "404" in resp.json()["detail"]


def test_fetch_endpoint_empty_extraction_rejected(client, monkeypatch):
    monkeypatch.setattr(
        httpx, "get", lambda *a, **k: FakeResponse("<html><body><script>x</script></body></html>")
    )
    prop = make_property(client, "Empty Fetch")
    resp = client.post(
        f"/api/content/{prop['id']}/homepage/fetch", json={"url": "https://example.com/blank"}
    )
    assert resp.status_code == 422
    assert "no readable text" in resp.json()["detail"]


def test_fetch_unknown_property_404(client, monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: FakeResponse(SAMPLE_HTML))
    resp = client.post("/api/content/999/homepage/fetch", json={"url": "https://example.com"})
    assert resp.status_code == 404
