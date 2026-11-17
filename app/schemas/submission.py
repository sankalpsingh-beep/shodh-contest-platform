from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


class SubmissionCreate(BaseModel):
    source_code: str = Field(min_length=1, max_length=100000)
    language: str = Field(default="python", pattern="^python$")


class SubmissionAcceptedResponse(BaseModel):
    id: UUID
    contest_id: UUID
    problem_id: UUID
    problem_version_id: UUID
    test_suite_version_id: UUID
    status: str
    created_at: datetime
    message: str


class SubmissionDetailResponse(BaseModel):
    id: UUID
    contest_id: UUID
    problem_id: UUID
    problem_version_id: UUID
    test_suite_version_id: UUID
    language: str
    status: str
    created_at: datetime
    attempt_number: int | None = None
    attempt_status: str | None = None
    verdict: str | None = None
    score: int | None = None
