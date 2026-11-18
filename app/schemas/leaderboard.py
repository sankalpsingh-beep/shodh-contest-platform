
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class LeaderboardEntry(BaseModel):
    rank: int
    user_id: UUID
    display_name: str
    score: int
    last_improved_at: datetime | None
