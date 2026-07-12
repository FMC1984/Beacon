from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ContentPageIn(BaseModel):
    page: str
    title: str
    body: str
    mapped_keyword: str | None = None
    source_url: str | None = None
    # Optional explicit last-updated (freshness signal); defaults to now.
    updated_at: datetime | None = None


class ContentFetchIn(BaseModel):
    url: str
    mapped_keyword: str | None = None


class ContentPageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    property_id: int
    page: str
    title: str
    body: str
    mapped_keyword: str | None
    source_url: str | None
    updated_at: datetime | None
    created_at: datetime


class ContentFetchOut(BaseModel):
    page: ContentPageOut
    char_count: int
    truncated: bool
