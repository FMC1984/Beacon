from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CompanyCreate(BaseModel):
    name: str
    slug: str | None = None


class CompanyUpdate(BaseModel):
    name: str | None = None


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    created_at: datetime
    property_count: int = 0
