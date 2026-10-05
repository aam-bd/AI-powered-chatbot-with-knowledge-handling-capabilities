"""Pydantic schemas for authentication, users, and standardized API responses."""
import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field, ConfigDict


class ErrorResponse(BaseModel):
    """Standardized API error response format per architecture §8."""
    detail: str
    code: str


class UserRegisterRequest(BaseModel):
    """User registration payload. Note: role is not accepted and always forced to 'user'."""
    email: EmailStr
    password: str = Field(..., min_length=6, description="Password with minimum 6 characters")
    # Optional role parameter to verify that even if supplied, it is discarded
    role: Optional[str] = None


class UserLoginRequest(BaseModel):
    """User login payload."""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """JWT Token response containing access and refresh tokens."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshTokenRequest(BaseModel):
    """Payload to request a new access token using a refresh token."""
    refresh_token: str


class UserResponse(BaseModel):
    """User profile response."""
    id: uuid.UUID
    email: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
