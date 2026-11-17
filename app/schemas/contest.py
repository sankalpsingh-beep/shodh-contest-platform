from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator

class ContestCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    description: str | None = None
    starts_at: datetime
    ends_at: datetime
    duration_minutes: int = Field(default=120, gt=0)
    is_published: bool = False

    @model_validator(mode="after")
    def validate_dates(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be later than starts_at")
        return self

class ContestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    title: str
    description: str | None
    starts_at: datetime
    ends_at: datetime
    duration_minutes: int
    is_published: bool

class MessageResponse(BaseModel):
    message: str
