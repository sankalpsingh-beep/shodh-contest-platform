from pydantic import BaseModel, Field

class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1)

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int

class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str
