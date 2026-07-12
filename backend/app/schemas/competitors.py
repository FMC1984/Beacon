from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CompetitorIn(BaseModel):
    name: str
    aliases: list[str] = []
    domain: str | None = None


class CompetitorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    property_id: int
    name: str
    aliases: list[str] | None
    domain: str | None
    created_at: datetime
    updated_at: datetime | None
