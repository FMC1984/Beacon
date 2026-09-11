"""Phase 19 (1a): URL normalization, citation extraction (provider first,
prose-regex fallback, never both) and source classification."""

from app.connectors.base import ProviderCitation, ProviderResult
from app.services.observatory.citations import (
    classify_citation,
    domain_of_url,
    extract_citations,
    normalize_url,
)


def test_normalize_url_strips_www_tracking_fragment_and_trailing_slash():
    normalized, domain, root, path = normalize_url(
        "https://WWW.Example.com/Denver/?utm_source=chatgpt&page=2#top"
    )
    assert domain == "example.com"
    assert root == "example.com"
    assert path == "/Denver"
    assert normalized == "example.com/Denver?page=2"


def test_normalize_url_accepts_bare_domain_and_second_level_tlds():
    normalized, domain, root, path = normalize_url("apartments.co.uk")
    assert (normalized, domain, root, path) == ("apartments.co.uk", "apartments.co.uk", "apartments.co.uk", None)
    _, domain, root, _ = normalize_url("https://blog.rentcafe.com/post/1")
    assert domain == "blog.rentcafe.com" and root == "rentcafe.com"
    assert normalize_url("") == ("", "", "", "")
    assert domain_of_url("https://www.solaracourt.com/") == "solaracourt.com"


def test_provider_citations_win_and_are_deduplicated():
    result = ProviderResult(
        text="see https://other.example.net in prose",
        provider="openai", platform="chatgpt",
        citations=(
            ProviderCitation(url="https://www.example.com/a?utm_x=1", title="A", start_index=1, end_index=5),
            ProviderCitation(url="https://example.com/a", title="A again"),
            ProviderCitation(url="https://apartments.com/denver", title="ILS"),
        ),
    )
    drafts = extract_citations(result, result.text)
    assert [d.normalized_url for d in drafts] == ["example.com/a", "apartments.com/denver"]
    assert [d.citation_order for d in drafts] == [0, 1]
    assert drafts[0].capture_method == "provider_annotation"
    # The prose URL is NOT mixed in when the provider reported citations.
    assert all(d.domain != "other.example.net" for d in drafts)


def test_prose_regex_fallback_when_provider_reports_nothing():
    text = "Check https://www.solaracourt.com/floor-plans and apartments.com for listings."
    result = ProviderResult(text=text, provider="legacy", platform="chatgpt")
    drafts = extract_citations(result, text)
    assert [d.domain for d in drafts] == ["solaracourt.com", "apartments.com"]
    assert all(d.capture_method == "prose_regex" for d in drafts)
    assert drafts[0].citation_position == text.find("https://www.solaracourt.com/floor-plans")


def test_classification_reuses_source_classifier_vocabulary():
    assert classify_citation("solaracourt.com", {"solaracourt.com"}, set()) == "owned"
    assert classify_citation("rival.com", set(), {"rival.com"}) == "competitor"
    assert classify_citation("apartments.com", set(), set()) == "directory"
    assert classify_citation("hud.gov", set(), set()) == "government"
    assert classify_citation("totally-unknown.io", set(), set()) == "unknown"
