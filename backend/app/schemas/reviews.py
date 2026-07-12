from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class ReviewIn(BaseModel):
    provider: str = "manual"
    external_review_id: str | None = None
    author_name: str | None = None
    rating: float | None = None
    title: str | None = None
    body: str
    review_date: date | None = None
    response_text: str | None = None
    response_date: date | None = None
    source_url: str | None = None


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    property_id: int
    provider: str
    external_review_id: str | None
    author_name: str | None
    rating: float | None
    title: str | None
    body: str
    review_date: date | None
    response_text: str | None
    response_date: date | None
    source_url: str | None
    created_at: datetime
    updated_at: datetime | None
