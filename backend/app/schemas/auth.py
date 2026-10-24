"""
Authentication & Officer Schemas
"""
from typing import Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    """User credentials for token authentication."""
    email: str = Field(..., description="Registered AICTE email address")
    password: str = Field(..., description="Account password")


class OfficerResponse(BaseModel):
    """Public profile of an authenticated AICTE officer."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: str
    bureau_id: Optional[int] = None
    region: Optional[str] = None
    is_active: bool


class TokenResponse(BaseModel):
    """Bearer token response upon successful login."""
    access_token: str
    token_type: str = "bearer"
    officer: OfficerResponse
