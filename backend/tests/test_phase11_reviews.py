"""Review storage, CRUD API, filtering, provider, and empty states."""

from datetime import date

from app.connectors.development import DevelopmentDataProvider
from app.models import PropertyReview
from tests.test_phase2_uploads import make_property


def create_review(client, property_id, **fields):
    body = {"body": fields.pop("body", "A review."), **fields}
    return client.post(f"/api/reviews/{property_id}", json=body)


def test_create_and_list(client, db):
    prop = make_property(client, "Rev Property")
    resp = create_review(client, prop["id"], rating=4.5, title="Nice", body="Clean and quiet.",
                         provider="google", external_review_id="g1", review_date="2026-06-01")
    assert resp.status_code == 201, resp.text
    assert resp.json()["rating"] == 4.5
    listing = client.get(f"/api/reviews/{prop['id']}").json()
    assert len(listing) == 1


def test_property_scoping(client, db):
    a = make_property(client, "Rev A")
    b = make_property(client, "Rev B")
    create_review(client, a["id"], body="A review.")
    assert len(client.get(f"/api/reviews/{a['id']}").json()) == 1
    assert len(client.get(f"/api/reviews/{b['id']}").json()) == 0


def test_two_null_external_ids_both_persist(client, db):
    prop = make_property(client, "Null Ext")
    r1 = create_review(client, prop["id"], body="First manual review.", provider="manual")
    r2 = create_review(client, prop["id"], body="Second manual review.", provider="manual")
    assert r1.status_code == 201 and r2.status_code == 201
    assert db.query(PropertyReview).filter_by(property_id=prop["id"]).count() == 2


def test_duplicate_non_null_external_id_rejected(client, db):
    prop = make_property(client, "Dup Ext")
    create_review(client, prop["id"], body="One.", provider="google", external_review_id="g1")
    dup = create_review(client, prop["id"], body="Two.", provider="google", external_review_id="g1")
    assert dup.status_code == 409


def test_update_and_delete(client, db):
    prop = make_property(client, "Rev Edit")
    rid = create_review(client, prop["id"], rating=2, body="Bad.").json()["id"]
    upd = client.put(f"/api/reviews/{prop['id']}/{rid}", json={"rating": 5, "body": "Actually great."})
    assert upd.status_code == 200 and upd.json()["rating"] == 5
    dele = client.delete(f"/api/reviews/{prop['id']}/{rid}")
    assert dele.status_code == 200
    assert db.query(PropertyReview).count() == 0


def test_filters(client, db):
    prop = make_property(client, "Rev Filter")
    create_review(client, prop["id"], rating=5, body="A.", provider="google", review_date="2026-06-01")
    create_review(client, prop["id"], rating=2, body="B.", provider="yelp", review_date="2026-05-01")
    create_review(client, prop["id"], rating=4, body="C.", provider="google", review_date="2026-04-01")

    assert len(client.get(f"/api/reviews/{prop['id']}?min_rating=4").json()) == 2
    assert len(client.get(f"/api/reviews/{prop['id']}?provider=yelp").json()) == 1
    assert len(client.get(f"/api/reviews/{prop['id']}?date_from=2026-05-15").json()) == 1
    assert len(client.get(f"/api/reviews/{prop['id']}?max_rating=3").json()) == 1


def test_empty_state(client, db):
    prop = make_property(client, "Rev Empty")
    assert client.get(f"/api/reviews/{prop['id']}").json() == []


def test_provider_returns_scoped_reviews(client, db):
    prop = make_property(client, "Rev Provider")
    create_review(client, prop["id"], rating=4, body="Great staff.", review_date="2026-06-01")
    records = DevelopmentDataProvider().get_reviews(db, prop["id"])
    assert len(records) == 1
    assert records[0].text == "Great staff."
    assert records[0].review_id is not None


def test_provider_empty_stable(client, db):
    prop = make_property(client, "Rev Provider Empty")
    assert DevelopmentDataProvider().get_reviews(db, prop["id"]) == []
