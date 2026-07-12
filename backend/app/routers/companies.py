"""Company CRUD. A company groups properties; deleting one unassigns its
properties (sets company_id NULL) rather than deleting them, so no property
data is ever lost by removing a company."""

import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Company, Property
from app.schemas.companies import CompanyCreate, CompanyOut, CompanyUpdate

router = APIRouter(prefix="/companies", tags=["companies"])


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug:
        raise HTTPException(status_code=422, detail="Name produces an empty slug.")
    return slug


def _counts(db: Session) -> dict[int, int]:
    rows = (
        db.query(Property.company_id, func.count(Property.id))
        .filter(Property.company_id.isnot(None))
        .group_by(Property.company_id)
        .all()
    )
    return {cid: n for cid, n in rows}


def _to_out(company: Company, counts: dict[int, int]) -> CompanyOut:
    out = CompanyOut.model_validate(company)
    out.property_count = counts.get(company.id, 0)
    return out


@router.get("", response_model=list[CompanyOut])
def list_companies(db: Session = Depends(get_db)):
    counts = _counts(db)
    return [
        _to_out(c, counts)
        for c in db.query(Company).order_by(Company.name).all()
    ]


@router.post("", response_model=CompanyOut, status_code=201)
def create_company(payload: CompanyCreate, db: Session = Depends(get_db)):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Company name is required.")
    slug = payload.slug or _slugify(name)
    exists = (
        db.query(Company)
        .filter((Company.name == name) | (Company.slug == slug))
        .first()
    )
    if exists:
        raise HTTPException(
            status_code=409, detail="A company with that name already exists."
        )
    company = Company(name=name, slug=slug)
    db.add(company)
    db.commit()
    db.refresh(company)
    return _to_out(company, {})


@router.patch("/{company_id}", response_model=CompanyOut)
def update_company(
    company_id: int, payload: CompanyUpdate, db: Session = Depends(get_db)
):
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found.")
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Company name is required.")
        clash = (
            db.query(Company)
            .filter(Company.name == name, Company.id != company_id)
            .first()
        )
        if clash:
            raise HTTPException(
                status_code=409, detail="A company with that name already exists."
            )
        company.name = name
        company.slug = _slugify(name)
    db.commit()
    db.refresh(company)
    return _to_out(company, _counts(db))


@router.delete("/{company_id}", status_code=200)
def delete_company(company_id: int, db: Session = Depends(get_db)):
    """Remove the company and unassign its properties (company_id -> NULL).
    Property data is untouched."""
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found.")
    unassigned = (
        db.query(Property)
        .filter(Property.company_id == company_id)
        .update({Property.company_id: None}, synchronize_session=False)
    )
    db.delete(company)
    db.commit()
    return {"status": "deleted", "company_id": company_id, "unassigned": unassigned}
