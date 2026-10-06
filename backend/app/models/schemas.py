"""Pydantic schemas for authentication, users, and standardized API responses."""
import uuid
from datetime import datetime, timezone
from enum import Enum
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


class DocumentUrlCreateRequest(BaseModel):
    """Payload to ingest a web URL."""
    url: str
    name: Optional[str] = None


class DocumentResponse(BaseModel):
    """Representation of a document and its lifecycle metadata."""
    id: uuid.UUID
    name: str
    source_type: str
    source_uri: str
    sha256: str
    size_bytes: int
    status: str
    active_version: Optional[int] = None
    pending_version: Optional[int] = None
    last_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentStatusResponse(BaseModel):
    """Document status and lifecycle check response."""
    id: uuid.UUID
    name: str
    status: str
    active_version: Optional[int] = None
    pending_version: Optional[int] = None
    last_error: Optional[str] = None
    heartbeat_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class DocumentAcceptedResponse(BaseModel):
    """Accepted (202) response for asynchronous background document ingestion/deletion."""
    document_id: str
    task_id: Optional[str] = None
    status: str = "accepted"
    message: str


# ------------------------------------------------------------------------------
# Chat & Conversation Memory Schemas (Phase 4)
# ------------------------------------------------------------------------------

class MessageKind(str, Enum):
    """Kind marker for conversation turns to prevent treating fallbacks as knowledge."""
    NORMAL = "normal"
    FALLBACK = "fallback"
    CLARIFY = "clarify"


class ChatMessage(BaseModel):
    """Individual turn stored in Redis session memory."""
    role: str  # "user" | "assistant"
    content: str
    kind: MessageKind = MessageKind.NORMAL
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class SessionSummaryResponse(BaseModel):
    """Summary representation of an active chat session."""
    session_id: str
    message_count: int
    last_message_preview: Optional[str] = None
    updated_at: datetime


class SessionDeleteResponse(BaseModel):
    """Response returned upon clearing a session."""
    detail: str
    session_id: str


class RouterIntent(str, Enum):
    """Possible intent classifications produced by the intent router."""
    GREETING = "GREETING"
    CLARIFY = "CLARIFY"
    SEARCH = "SEARCH"


class RouterDecision(BaseModel):
    """JSON output schema produced by the FAST model and validated with Pydantic."""
    intent: RouterIntent
    clarification_message: Optional[str] = None
    standalone_query: Optional[str] = None

