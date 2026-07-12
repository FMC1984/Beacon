"""Deterministic Review Intelligence analysis: sentiment, themes, severity,
opportunities, trends (anchoring + thresholds), marketing, scoring, gating."""

from datetime import date, datetime, timezone

from app.models import Property, PropertyReview, PropertyProfile
from app.services.review_intelligence import analyze_property_reviews
from app.services.review_intelligence.analyzer import _classify_sentiment
from app.services.review_intelligence.matching import sentiment_terms

TODAY = date(2026, 7, 5)


def make_prop(db, name="Rev Analysis"):
    p = Property(name=name, slug=name.lower().replace(" ", "-"))
    db.add(p)
    db.commit()
    return p


def add_review(db, pid, rating, body, d, title=None, response=None, provider="manual"):
    db.add(PropertyReview(property_id=pid, provider=provider, rating=rating, body=body,
                          title=title, review_date=d, response_text=response))
    db.commit()


def set_context(db, pid, **fields):
    db.add(PropertyProfile(property_id=pid, **fields))
    db.commit()


# --- determinism ---


def test_analysis_deterministic(db):
    p = make_prop(db)
    add_review(db, p.id, 5, "Friendly staff and clean.", date(2026, 6, 1))
    add_review(db, p.id, 2, "Parking is terrible and rude staff.", date(2026, 6, 2))
    a1 = analyze_property_reviews(db, p.id, today=TODAY)
    a2 = analyze_property_reviews(db, p.id, today=TODAY)
    assert a1 == a2


def test_no_reviews_empty_state(db):
    p = make_prop(db)
    a = analyze_property_reviews(db, p.id, today=TODAY)
    assert a["has_reviews"] is False
    assert a["score"] is None


# --- sentiment + distribution ---


def test_rating_and_distribution_with_null(db):
    p = make_prop(db)
    add_review(db, p.id, 4.5, "Good.", date(2026, 6, 1))  # rounds to 5
    add_review(db, p.id, None, "The dishwasher broke.", date(2026, 6, 2))
    a = analyze_property_reviews(db, p.id, today=TODAY)
    dist = a["overview"]["rating_distribution"]
    assert dist["5"] == 1
    assert dist["no_rating"] == 1
    assert sum(dist.values()) == a["overview"]["total_reviews"]
    assert a["overview"]["average_rating"] == 4.5  # only rated review counts


def test_strong_negative_term_overrides_high_rating(db):
    p = make_prop(db)
    add_review(db, p.id, 5, "Infestation of roaches everywhere.", date(2026, 6, 1))
    a = analyze_property_reviews(db, p.id, today=TODAY)
    # 5 stars but a strong-negative term -> negative.
    assert a["overview"]["sentiment_breakdown"]["negative"] == 1


def test_null_rating_classified_by_terms(db):
    terms = sentiment_terms()

    class R:
        rating = None
        title = ""
        text = "This place is terrible and dirty."
    assert _classify_sentiment(R(), terms) == "negative"


def test_response_rate_omitted_when_zero(db):
    p = make_prop(db)
    add_review(db, p.id, 4, "Fine.", date(2026, 6, 1))
    a = analyze_property_reviews(db, p.id, today=TODAY)
    assert "response_rate" not in a["overview"]


# --- themes ---


def test_theme_mixed_counted_once(db):
    p = make_prop(db)
    # One review, one theme (staff), both a positive and negative staff term.
    add_review(db, p.id, 3, "The staff is great but the office is rude.", date(2026, 6, 1))
    a = analyze_property_reviews(db, p.id, today=TODAY)
    staff = next(t for t in a["themes"] if t["theme"] == "staff_service")
    assert staff["mention_count"] == 1  # counted once
    assert staff["mixed"] == 1


def test_negated_positive_counts_negative(db):
    # Phase 15a fixed the old literal-matching limitation: "not very clean"
    # now counts as a cleanliness COMPLAINT (negated positive flips), not
    # praise.
    p = make_prop(db)
    add_review(db, p.id, 3, "The apartment is not very clean.", date(2026, 6, 1))
    a = analyze_property_reviews(db, p.id, today=TODAY)
    clean = next((t for t in a["themes"] if t["theme"] == "cleanliness"), None)
    assert clean is not None
    assert clean["positive"] == 0
    assert clean["negative"] == 1


def test_absence_phrase_is_not_a_mention(db):
    # "I did not have a maintenance issue" is not a maintenance complaint or
    # even a maintenance mention (absence phrase excludes the term).
    p = make_prop(db)
    add_review(db, p.id, 5, "Great year here. I did not have a maintenance issue.", date(2026, 6, 1))
    a = analyze_property_reviews(db, p.id, today=TODAY)
    assert next((t for t in a["themes"] if t["theme"] == "maintenance"), None) is None


def test_plain_negation_never_cancels_a_complaint(db):
    # "never fixed my broken heater" must stay a maintenance complaint; plain
    # cues only flip positive terms, they never cancel negative ones.
    p = make_prop(db)
    add_review(db, p.id, 1, "Maintenance never fixed my broken heater.", date(2026, 6, 1))
    a = analyze_property_reviews(db, p.id, today=TODAY)
    maint = next(t for t in a["themes"] if t["theme"] == "maintenance")
    assert maint["negative"] == 1


def test_severity_multiplier_for_pest(db):
    p = make_prop(db)
    add_review(db, p.id, 1, "Roaches everywhere, infestation.", date(2026, 6, 1))
    a = analyze_property_reviews(db, p.id, today=TODAY)
    pest = next(o for o in a["opportunities"] if o["theme"] == "pest")
    # pest severity_weight 4 x multiplier 2 x recency weight 1.5 = 12
    assert pest["severity"] == 12.0
    assert pest["severity_level"] == "High"


def test_opportunities_prioritized(db):
    p = make_prop(db)
    add_review(db, p.id, 1, "Maintenance never fixed my broken heater, still not fixed.", date(2026, 6, 1))
    add_review(db, p.id, 3, "Grounds are neglected and overgrown.", date(2026, 6, 2))
    a = analyze_property_reviews(db, p.id, today=TODAY)
    assert a["opportunities"][0]["priority"] == 1
    ranks = [(o["impact"], o["effort"]) for o in a["opportunities"]]
    assert ranks[0][0] in ("High", "Medium")
    for o in a["opportunities"]:
        assert "not derivable" not in o["suggested_action"]  # grounded action


# --- trends: anchoring + thresholds ---


def test_dormant_profile_not_declining(db):
    p = make_prop(db)
    # All reviews far older than 180 days before TODAY, clustered together.
    for i in range(4):
        add_review(db, p.id, 2, f"Old complaint {i} about parking.", date(2025, 1, 1 + i))
    a = analyze_property_reviews(db, p.id, today=TODAY)
    # Anchored to most recent review; prior window empty -> insufficient, not declining.
    assert a["trends"]["metrics"]["average_rating"]["status"] == "Insufficient data"


def test_per_theme_insufficient_while_global_sufficient(db):
    p = make_prop(db)
    # 4 recent + 4 prior reviews (global sufficient), but a rare theme only in one.
    for i in range(4):
        add_review(db, p.id, 4, f"Clean and friendly {i}.", date(2026, 6, 1 + i))
    for i in range(4):
        add_review(db, p.id, 4, f"Clean and friendly {i}.", date(2026, 2, 1 + i))
    add_review(db, p.id, 1, "Bed bugs infestation.", date(2026, 6, 10))
    a = analyze_property_reviews(db, p.id, today=TODAY)
    # Global metric determinable; pest theme has too few to trend -> not listed.
    assert a["trends"]["determinable"] is True
    assert "pest" not in a["trends"]["theme_trends"]


def test_insufficient_data_honest(db):
    p = make_prop(db)
    add_review(db, p.id, 4, "Good.", date(2026, 6, 1))
    a = analyze_property_reviews(db, p.id, today=TODAY)
    assert a["trends"]["metrics"]["average_rating"]["status"] == "Insufficient data"
    assert "not enough reviews" in a["trends"]["metrics"]["average_rating"]["note"]


# --- scoring ---


def test_score_explainable_and_labeled(db):
    p = make_prop(db)
    add_review(db, p.id, 5, "Friendly staff, clean, love it here.", date(2026, 6, 1))
    add_review(db, p.id, 4, "Responsive maintenance.", date(2026, 6, 2))
    a = analyze_property_reviews(db, p.id, today=TODAY)
    s = a["score"]
    assert 0 <= s["value"] <= 100
    assert s["label"] in ("Critical", "Needs Attention", "Basic", "Healthy", "Excellent")
    assert all(b["explanation"] for b in s["breakdown"])
    # Weights are display-rounded to 2dp; allow a small rounding drift.
    assert abs(sum(b["weight"] for b in s["breakdown"]) - 1.0) < 0.02


# --- marketing + context gating ---


def test_regulated_suppresses_restricted_marketing(db):
    p = make_prop(db)
    set_context(db, p.id, property_type="affordable", is_regulated=True,
                regulatory_programs=["LIHTC"])
    add_review(db, p.id, 5, "Friendly staff, clean, love it here.", date(2026, 6, 1))
    a = analyze_property_reviews(db, p.id, today=TODAY)
    guidance = {g["theme"]: g["status"] for g in a["marketing"]["context_guidance"]}
    # Even with strongly positive sentiment, restricted themes are suppressed.
    assert guidance.get("exclusivity") == "suppressed"
    assert guidance.get("young_professional") == "suppressed"
    assert a["marketing"]["compliance"]["level"] == "caution"


def test_unknown_status_withholds(db):
    p = make_prop(db)
    add_review(db, p.id, 5, "Great and clean.", date(2026, 6, 1))
    a = analyze_property_reviews(db, p.id, today=TODAY)
    assert a["marketing"]["compliance"]["level"] == "withheld"
    assert "not specified" in a["marketing"]["compliance"]["message"]


def test_student_quiet_is_caution(db):
    p = make_prop(db)
    set_context(db, p.id, property_type="student", is_regulated=False)
    add_review(db, p.id, 5, "Very quiet and peaceful community.", date(2026, 6, 1))
    a = analyze_property_reviews(db, p.id, today=TODAY)
    quiet = next(i for i in a["marketing"]["insights"] if i["theme"] == "quiet_atmosphere")
    assert quiet["gating_status"] == "caution-only"
    assert quiet["caution"] is True
