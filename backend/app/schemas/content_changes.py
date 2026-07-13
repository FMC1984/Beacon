from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models.content_change import ChangeType


class ContentChangeIn(BaseModel):
    change_title: str
    change_type: ChangeType
    date_implemented: date
    page_url: str | None = None
    notes: str | None = None
    related_opportunity: str | None = None
    created_by: str | None = None
    before_snapshot_ref: str | None = None
    after_snapshot_ref: str | None = None


class ContentChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    property_id: int
    company_id: int | None
    change_title: str
    change_type: ChangeType
    date_implemented: date
    page_url: str | None
    notes: str | None
    related_opportunity: str | None
    created_by: str | None
    before_snapshot_ref: str | None
    after_snapshot_ref: str | None
    created_at: datetime
