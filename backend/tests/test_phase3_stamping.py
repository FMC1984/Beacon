from app.cli.backfill_ai import backfill
from app.constants import AI_TRAFFIC_DISCLOSURE
from app.models import GA4SessionsDaily
from tests.test_phase2_uploads import make_property, post_upload


def test_ingest_stamps_ai_rows(client, db):
    prop = make_property(client)
    resp = post_upload(client, "ga4", prop["id"], "ga4_traffic_with_date.csv")
    assert resp.status_code == 201

    rows = {r.session_source: r for r in db.query(GA4SessionsDaily).all()}
    assert rows["chatgpt.com"].is_ai_referral is True
    assert rows["chatgpt.com"].ai_platform == "chatgpt"
    assert rows["perplexity.ai"].is_ai_referral is True
    assert rows["perplexity.ai"].ai_platform == "perplexity"
    assert rows["google"].is_ai_referral is False
    assert rows["google"].ai_platform is None
    assert rows["(direct)"].is_ai_referral is False


def test_upload_response_carries_ai_count_with_disclosure(client):
    prop = make_property(client)
    body = post_upload(client, "ga4", prop["id"], "ga4_traffic_with_date.csv").json()
    assert body["ai_rows_detected"] == 2
    # Hard rule 3: an AI traffic number never travels without the exact disclosure.
    assert body["disclosure"] == AI_TRAFFIC_DISCLOSURE


def test_gsc_upload_has_no_ai_fields(client):
    prop = make_property(client)
    body = post_upload(client, "gsc", prop["id"], "gsc_dates.csv").json()
    assert body["ai_rows_detected"] is None
    assert body["disclosure"] is None


def test_backfill_restamps_stale_rows(client, db):
    prop = make_property(client)
    post_upload(client, "ga4", prop["id"], "ga4_traffic_with_date.csv")

    # Simulate rows ingested under an older reference list: wipe the stamps.
    db.query(GA4SessionsDaily).update(
        {"is_ai_referral": False, "ai_platform": None}
    )
    db.commit()

    summary = backfill(db)
    assert summary["rows_scanned"] == 5
    assert summary["rows_changed"] == 2
    assert summary["ai_rows_total"] == 2
    assert summary["platform_counts"] == {"chatgpt": 1, "perplexity": 1}

    rows = {r.session_source: r for r in db.query(GA4SessionsDaily).all()}
    assert rows["chatgpt.com"].ai_platform == "chatgpt"
    assert rows["google"].is_ai_referral is False


def test_backfill_is_idempotent(client, db):
    prop = make_property(client)
    post_upload(client, "ga4", prop["id"], "ga4_traffic_with_date.csv")
    first = backfill(db)
    assert first["rows_changed"] == 0  # ingest already stamped correctly
    second = backfill(db)
    assert second["rows_changed"] == 0
    assert second["ai_rows_total"] == 2
