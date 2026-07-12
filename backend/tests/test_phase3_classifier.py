import json

import pytest

from app.services.classifier import (
    REFERENCE_PATH,
    AIReferralClassifier,
    get_classifier,
)
from app.services.ingestion.common import UploadValidationError
from app.services.ingestion.ga4 import parse_ga4_csv
from tests.conftest import fixture_bytes


@pytest.fixture(scope="module")
def clf() -> AIReferralClassifier:
    return AIReferralClassifier.from_reference_file()


def test_reference_json_is_well_formed():
    raw = json.loads(REFERENCE_PATH.read_text())
    assert raw["version"]
    assert len(raw["platforms"]) >= 10
    for p in raw["platforms"]:
        assert p["key"] and p["label"]
        assert isinstance(p["referrer_domains"], list)
        assert isinstance(p["utm_sources"], list)


def test_domain_and_subdomain_matching(clf):
    assert clf.classify("chatgpt.com") == "chatgpt"
    assert clf.classify("chat.openai.com") == "chatgpt"
    assert clf.classify("www.perplexity.ai") == "perplexity"
    assert clf.classify("copilot.microsoft.com") == "copilot"
    assert clf.classify("gemini.google.com") == "gemini"
    assert clf.classify("claude.ai") == "claude"


def test_url_shaped_and_cased_sources_normalize(clf):
    assert clf.classify("https://chatgpt.com/") == "chatgpt"
    assert clf.classify("ChatGPT.com") == "chatgpt"
    assert clf.classify("https://www.perplexity.ai/search?q=x") == "perplexity"


def test_utm_source_tags_match(clf):
    assert clf.classify("chatgpt") == "chatgpt"
    assert clf.classify("perplexity") == "perplexity"
    assert clf.classify("gemini") == "gemini"


def test_non_ai_sources_do_not_match(clf):
    for source in (
        "google",
        "google.com",
        "bing",
        "facebook.com",
        "(direct)",
        "duckduckgo.com",
        "x.com",
        "newsletter",
        "chatgpt.com.evil.example",
    ):
        assert clf.classify(source) is None, source


def test_google_never_matches_via_gemini_suffix(clf):
    # gemini.google.com is listed; bare google properties must stay unmatched.
    assert clf.classify("google.com") is None
    assert clf.classify("news.google.com") is None


def test_empty_sources(clf):
    assert clf.classify(None) is None
    assert clf.classify("") is None
    assert clf.classify("   ") is None


def test_parse_does_not_classify_but_ingest_does(client, db):
    # Parser output has no stamps; classification happens at ingest.
    parsed = parse_ga4_csv(fixture_bytes("ga4_traffic_with_date.csv"))
    assert all("is_ai_referral" not in r for r in parsed.rows)


def test_real_export_shape_channel_group_rejected():
    # Mirrors the structure of a real GA4 UI export (channel group dimension,
    # no Date, no Session source): must be rejected with export instructions,
    # never guessed into the daily source/medium grain.
    with pytest.raises(UploadValidationError, match="Date"):
        parse_ga4_csv(fixture_bytes("ga4_channel_group_no_date.csv"))


def test_get_classifier_is_cached():
    assert get_classifier() is get_classifier()
