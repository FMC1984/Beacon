"""Tenancy helpers (Phase 19, slice 1b).

The single place that knows how a property resolves to an organization.
Today everything belongs to the default organization; when real tenancy
arrives, a request-scoped principal plugs in here and nothing else moves.
"""

from sqlalchemy.orm import Session

from app.models import Company, Organization, Property
from app.models.organization import DEFAULT_ORGANIZATION_SLUG


def default_organization(db: Session) -> Organization:
    org = db.query(Organization).filter_by(slug=DEFAULT_ORGANIZATION_SLUG).one_or_none()
    if org is None:
        org = Organization(name="Beacon", slug=DEFAULT_ORGANIZATION_SLUG, is_active=True)
        db.add(org)
        db.commit()
        db.refresh(org)
    return org


def default_organization_id(db: Session) -> int:
    return default_organization(db).id


def property_org_id(db: Session, property_id: int) -> int:
    """Property -> Company -> Organization, falling back to the default org
    for unassigned properties or companies created before organizations."""
    prop = db.get(Property, property_id)
    if prop is not None and prop.company_id is not None:
        company = db.get(Company, prop.company_id)
        if company is not None and company.organization_id is not None:
            return company.organization_id
    return default_organization_id(db)


def org_property_ids(db: Session, organization_id: int) -> list[int]:
    """Every active property under the organization's companies; unassigned
    properties belong to the default organization."""
    company_ids = [
        c.id for c in db.query(Company.id).filter(Company.organization_id == organization_id)
    ]
    q = db.query(Property.id).filter(Property.is_active.is_(True))
    if organization_id == default_organization_id(db):
        q = q.filter((Property.company_id.in_(company_ids)) | (Property.company_id.is_(None)))
    else:
        q = q.filter(Property.company_id.in_(company_ids))
    return [pid for (pid,) in q.all()]
