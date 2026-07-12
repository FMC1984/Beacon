from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AIVisibilityQueryIn(BaseModel):
    prompt: str
    platform: str


class AIVisibilityQueryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    property_id: int
    platform: str
    prompt_text: str
    raw_response_text: str
    executed_at: datetime
    brand_mentioned: bool
    sources_cited: list[str] | None
    created_at: datetime
