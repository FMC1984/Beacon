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
    execution_status: str = "success"
    property_mention_count: int = 0
    competitor_mention_count: int = 0
    # Phase 19 Observatory links; None on rows stored before the run ledger.
    run_id: int | None = None
    prompt_id: int | None = None
    run_scope: str = "property"
    provider: str | None = None
    model: str | None = None
