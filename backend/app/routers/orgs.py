"""Platform-admin management of organizations (create clients, overrides)."""

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.deps import require_platform_admin
from app.db import get_db
from app.models import Company, Organization, OrgMembership
from app.services.billing.entitlement import entitlement

router = APIRouter(prefix="/admin/orgs", tags=["orgs"], dependencies=[Depends(require_platform_admin)])


class OrgCreate(BaseModel):
    name: str
    slug: str | None = None


class BillingOverride(BaseModel):
    active: bool
    reason: str | None = None


class OrgPatch(BaseModel):
    name: str | None = None
    is_active: bool | None = None
    billing_override: BillingOverride | None = None
    clear_billing_override: bool = False


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug:
        raise HTTPException(status_code=422, detail="Name produces an empty slug.")
    return slug


def _out(db: Session, org: Organization) -> dict:
    members = db.query(func.count(OrgMembership.id)).filter(OrgMembership.organization_id == org.id).scalar() or 0
    companies = db.query(func.count(Company.id)).filter(Company.organization_id == org.id).scalar() or 0
    ent = entitlement(db, org.id)
    return {
        "id": org.id, "name": org.name, "slug": org.slug, "is_active": org.is_active,
        "sample_data": bool((org.settings or {}).get("sample_data")),
        "billing_override": (org.settings or {}).get("billing_override"),
        "members": members, "companies": companies,
        "entitlement": ent.to_dict(),
        "created_at": org.created_at.isoformat() if org.created_at else None,
    }


@router.get("")
def list_orgs(db: Session = Depends(get_db)):
    return {"organizations": [_out(db, o) for o in db.query(Organization).order_by(Organization.name).all()]}


@router.post("", status_code=201)
def create_org(payload: OrgCreate, db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name is required.")
    slug = payload.slug or _slugify(name)
    if db.query(Organization).filter((Organization.slug == slug) | (Organization.name == name)).first():
        raise HTTPException(status_code=409, detail="An organization with that name or slug already exists.")
    org = Organization(name=name, slug=slug, is_active=True, settings={})
    db.add(org)
    db.commit()
    db.refresh(org)
    return _out(db, org)


@router.patch("/{org_id}")
def patch_org(org_id: int, payload: OrgPatch, db: Session = Depends(get_db)):
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found.")
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Name is required.")
        org.name = name
    if payload.is_active is not None:
        org.is_active = payload.is_active
    # Merge, never replace: settings also carries sample_data, budgets, white-label.
    merged = dict(org.settings or {})
    if payload.clear_billing_override:
        merged.pop("billing_override", None)
    elif payload.billing_override is not None:
        merged["billing_override"] = {"active": payload.billing_override.active,
                                      "reason": payload.billing_override.reason}
    org.settings = merged
    db.commit()
    db.refresh(org)
    return _out(db, org)
