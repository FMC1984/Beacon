"""Connector architecture: DevelopmentDataProvider returns normalized records
from local data, and the review/content extension points return empty."""

from datetime import datetime

from app.connectors import (
    ContentProvider,
    ContentRecord,
    DevelopmentDataProvider,
    LeadProvider,
    LeaseProvider,
    ReviewProvider,
    TrafficProvider,
)
from tests.test_phase2_uploads import make_property, post_upload
from tests.test_phase5_crm import post_crm


def test_development_provider_implements_all_interfaces():
    p = DevelopmentDataProvider()
    assert isinstance(p, TrafficProvider)
    assert isinstance(p, LeadProvider)
    assert isinstance(p, LeaseProvider)
    assert isinstance(p, ReviewProvider)
    assert isinstance(p, ContentProvider)


def test_get_traffic_normalizes_rows(client, db):
    prop = make_property(client, "Conn Property")
    post_upload(client, "ga4", prop["id"], "ga4_traffic_with_date.csv")
    records = DevelopmentDataProvider().get_traffic(db, prop["id"])
    assert len(records) == 5
    ai = [r for r in records if r.is_ai_referral]
    assert {r.ai_platform for r in ai} == {"chatgpt", "perplexity"}
    assert all(r.property_id == prop["id"] for r in records)


def test_get_leads_and_leases(client, db):
    prop = make_property(client, "Conn CRM")
    post_crm(client, prop["id"], "crm_yardi_placeholder.csv")
    leads = DevelopmentDataProvider().get_leads(db, prop["id"])
    leases = DevelopmentDataProvider().get_leases(db, prop["id"])
    assert len(leads) == 3
    # Only the one lead with a signed lease date is a lease.
    assert len(leases) == 1
    assert leases[0].lease_signed_date is not None


def test_reviews_and_content_are_empty_extension_points(client, db):
    prop = make_property(client, "Conn Empty")
    p = DevelopmentDataProvider()
    assert p.get_reviews(db, prop["id"]) == []
    assert p.get_content(db, prop["id"]) == []


class FakeContentProvider(ContentProvider):
    """Proves the content path works end to end once a real content connector
    exists; used by the chunker tests."""

    def get_content(self, db, property_id):
        return [
            ContentRecord(
                property_id=property_id,
                page="homepage",
                title="Welcome",
                body="Luxury apartments in Tempe with resort amenities.",
                updated_at=datetime(2026, 6, 15, 12, 0, 0),
            )
        ]
