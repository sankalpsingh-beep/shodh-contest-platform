from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, model_validator


class TestCaseCreate(BaseModel):
    input_data: str
    expected_output: str
    is_hidden: bool = True


class ProblemCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=100, pattern=r"^[a-z0-9-]+$")
    title: str = Field(min_length=2, max_length=200)
    statement: str = Field(min_length=10)
    input_description: str = ""
    output_description: str = ""
    points: int = Field(default=100, ge=0)
    time_limit_ms: int = Field(default=2000, gt=0, le=30000)
    memory_limit_mb: int = Field(default=256, gt=0, le=2048)
    test_cases: list[TestCaseCreate] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def require_public_example(self):
        if not any(not case.is_hidden for case in self.test_cases):
            raise ValueError("At least one public sample test case is required")
        return self


class ProblemUpdate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    statement: str = Field(min_length=10)
    input_description: str = ""
    output_description: str = ""
    points: int = Field(default=100, ge=0)
    time_limit_ms: int = Field(default=2000, gt=0, le=30000)
    memory_limit_mb: int = Field(default=256, gt=0, le=2048)
    test_cases: list[TestCaseCreate] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def require_public_example(self):
        if not any(not case.is_hidden for case in self.test_cases):
            raise ValueError("At least one public sample test case is required")
        return self


class ProblemResponse(BaseModel):
    id: UUID
    contest_id: UUID
    slug: str
    title: str
    version: int
    statement: str
    input_description: str
    output_description: str
    points: int
    time_limit_ms: int
    memory_limit_mb: int
    sample_test_cases: list[dict]


class ProblemCreatedResponse(BaseModel):
    id: UUID
    slug: str
    title: str
    version: int
    test_case_count: int


class OrganizerTestCaseResponse(BaseModel):
    position: int
    input_data: str
    expected_output: str
    is_hidden: bool
