"""Phase 18C: property-vs-portfolio-average Share of Voice comparison.
Hard-gated off - never a fabricated benchmark - unless at least 2 other
active, competitor-tracked properties in the same company have a sufficient
Share of Voice sample in the window."""

from datetime import datetime, timezone

from app.connectors.base import AIVisibilityQueryProvider
from app.models import Company, Competitor, Property
from app.services.ai_visibility import run_query
from app.services.reporting_share_of_voice import portfolio_average_sov


class FR(AIVisibilityQueryProvider):
    def __init__(self, response):
        self.response = response

    def execute_query(self, prompt, platform):
        return self.response

    def get_queries(self, db, property_id):
        return []


TODAY = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def _company(db, name="Portfolio Co"):
    c = Company(name=name, slug=name.lower().replace(" ", "-"))
    db.add(c)
    db.commit()
    return c


def _prop_with_sov(db, company, name):
    p = Property(name=name, slug=name.lower().replace(" ", "-"), company_id=company.id)
    db.add(p)
    db.commit()
    comp = Competitor(property_id=p.id, name=f"Rival of {name}")
    db.add(comp)
    db.commit()
    for _ in range(3):
        run_query(
            db, p.id, "How is the property?", "chatgpt",
            provider=FR(f"{p.name} is nice."), now=TODAY,
        )
    return p


def test_no_company_is_gated_off(db):
    p = Property(name="Standalone Court", slug="standalone-court")
    db.add(p)
    db.commit()
    result = portfolio_average_sov(db, p.id, days=30, today=TODAY.date())
    assert result == {"available": False, "reason": "no_company"}


def test_no_siblings_is_gated_off(db):
    company = _company(db)
    p = _prop_with_sov(db, company, "Only Court")
    result = portfolio_average_sov(db, p.id, days=30, today=TODAY.date())
    assert result["available"] is False
    assert result["property_count"] == 0


def test_one_sibling_is_still_gated_off(db):
    """A single comparison point is not a benchmark - the gate requires 2."""
    company = _company(db)
    p = _prop_with_sov(db, company, "Main Court")
    _prop_with_sov(db, company, "Sibling Court")
    result = portfolio_average_sov(db, p.id, days=30, today=TODAY.date())
    assert result["available"] is False
    assert result["property_count"] == 1


def test_two_siblings_unlocks_the_average(db):
    company = _company(db)
    p = _prop_with_sov(db, company, "Main Court Two")
    _prop_with_sov(db, company, "Sibling A")
    _prop_with_sov(db, company, "Sibling B")
    result = portfolio_average_sov(db, p.id, days=30, today=TODAY.date())
    assert result["available"] is True
    assert result["property_count"] == 2
    assert 0 <= result["average_share_of_voice"] <= 1


def test_sibling_without_competitors_is_excluded(db):
    company = _company(db)
    p = _prop_with_sov(db, company, "Main Court Three")
    _prop_with_sov(db, company, "Sibling C")
    # A sibling with no competitors tracked can never produce a Share of
    # Voice figure and must not be silently counted as "0 data points".
    no_comp = Property(
        name="No Competitor Sibling", slug="no-competitor-sibling", company_id=company.id
    )
    db.add(no_comp)
    db.commit()
    result = portfolio_average_sov(db, p.id, days=30, today=TODAY.date())
    assert result["available"] is False
    assert result["property_count"] == 1
