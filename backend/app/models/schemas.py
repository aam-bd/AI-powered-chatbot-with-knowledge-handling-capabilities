"""Pydantic schemas for authentication, users, and standardized API responses."""
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, EmailStr, Field, ConfigDict, model_validator


class ErrorResponse(BaseModel):
    """Standardized API error response format per architecture §8."""
    detail: str
    code: str


class MessageResponse(BaseModel):
    """Standardized API message response."""
    detail: str


class UserRegisterRequest(BaseModel):
    """User registration payload. Note: role is not accepted and always forced to 'user'."""
    email: EmailStr
    password: str = Field(..., min_length=10, description="Password with minimum 10 characters")
    # Optional role parameter to verify that even if supplied, it is discarded
    role: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    """Payload to update the user password."""
    current_password: str = Field(..., min_length=1, description="Current user password")
    new_password: str = Field(..., min_length=10, description="New password with minimum 10 characters")


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


class UserAdminUpdateRequest(BaseModel):
    """Payload for administrator updating user role or active status."""
    role: Optional[str] = Field(None, pattern="^(user|admin)$", description="User role ('user' | 'admin')")
    is_active: Optional[bool] = Field(None, description="Account active status")

    @model_validator(mode="after")
    def validate_at_least_one_field(self) -> "UserAdminUpdateRequest":
        if self.role is None and self.is_active is None:
            raise ValueError("At least one field ('role' or 'is_active') must be provided.")
        return self


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
    """Summary representation of a chat session."""
    id: uuid.UUID
    session_id: str
    title: str
    message_count: int = 0
    last_message_preview: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SessionRenameRequest(BaseModel):
    """Request payload for renaming a conversation."""
    title: str = Field(..., min_length=1, max_length=255, description="Updated session title")


class ChatMessageItemResponse(BaseModel):
    """Message item representation from persistent history."""
    id: int
    session_id: uuid.UUID
    role: str
    kind: str
    content: str
    citations: Optional[List[Dict[str, Any]]] = None
    fallback_layer: Optional[int] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


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


# ------------------------------------------------------------------------------
# SSE Streaming & Citations Schemas (Phase 4 Second Half)
# ------------------------------------------------------------------------------

class ChatStreamRequest(BaseModel):
    """Request payload for POST /api/v1/chat/stream."""
    session_id: Optional[str] = Field(None, max_length=128, description="Conversation session ID (optional; server creates session if omitted)")
    message: str = Field(..., min_length=1, description="User question or statement")


class CitationItem(BaseModel):
    """Single resolved source citation item for frontend drawer rendering."""
    tag: str = Field(..., description="Citation marker tag, e.g. C1")
    document: str = Field(..., description="Document filename or display name")
    page: Optional[int] = Field(None, description="Page number if applicable")
    section: Optional[str] = Field(None, description="Section heading if applicable")
    chunk_id: str = Field(..., description="Unique chunk point identifier")


class CitationsEventPayload(BaseModel):
    """Payload for SSE 'citations' event."""
    citations: List[CitationItem]


class RetractEventPayload(BaseModel):
    """Payload for SSE 'retract' event when answer is ungrounded."""
    text: str


class ErrorEventPayload(BaseModel):
    """Payload for SSE 'error' event."""
    message: str
    code: str


class DoneEventPayload(BaseModel):
    """Payload for SSE 'done' event terminating the response stream."""
    intent: str
    fallback_layer: Optional[int] = None


class TokenEventPayload(BaseModel):
    """Payload for SSE 'token' event."""
    text: str


# ------------------------------------------------------------------------------
# LLM Provider & Settings Schemas (Prompt 7e)
# ------------------------------------------------------------------------------

class LLMProviderCreate(BaseModel):
    """Admin request to register a new LLM provider."""
    name: str = Field(..., min_length=1, max_length=100)
    provider_type: str = Field(..., min_length=1, max_length=50)
    base_url: str = Field(..., min_length=1, max_length=500)
    api_key: Optional[str] = Field(None, description="Plaintext API key; encrypted at rest")
    models: List[str] = Field(..., min_length=1, description="List of supported model identifiers")
    default_model: str = Field(..., min_length=1, max_length=100)
    is_enabled: bool = True

    @model_validator(mode="after")
    def validate_models(self) -> "LLMProviderCreate":
        if self.default_model not in self.models:
            raise ValueError(f"default_model '{self.default_model}' must be in models list: {self.models}")
        return self


class LLMProviderUpdate(BaseModel):
    """Admin request to update an existing LLM provider."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    base_url: Optional[str] = Field(None, min_length=1, max_length=500)
    api_key: Optional[str] = Field(None, description="New API key (replaces existing if sent)")
    clear_api_key: Optional[bool] = Field(False, description="Explicitly remove stored API key")
    models: Optional[List[str]] = Field(None, min_length=1)
    default_model: Optional[str] = Field(None, min_length=1, max_length=100)
    is_enabled: Optional[bool] = None

    @model_validator(mode="after")
    def validate_models(self) -> "LLMProviderUpdate":
        if self.models is not None and self.default_model is not None:
            if self.default_model not in self.models:
                raise ValueError(f"default_model '{self.default_model}' must be in models list: {self.models}")
        return self


class LLMProviderResponse(BaseModel):
    """Safe provider details representation for admin dashboard."""
    id: uuid.UUID
    name: str
    provider_type: str
    base_url: str
    has_key: bool
    key_hint: Optional[str] = None
    models: List[str]
    default_model: str
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
    last_test_status: Optional[str] = None
    last_test_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class LLMProviderTestResponse(BaseModel):
    """Response payload for provider test connection endpoint."""
    success: bool
    status: str
    message: str
    sanitized_error: Optional[str] = None


class LLMModelsResponse(BaseModel):
    """Available models response for a provider."""
    provider_id: uuid.UUID
    models: List[str]
    source: str  # 'provider' | 'stored'


class LLMSettingsResponse(BaseModel):
    """Current runtime LLM selection and configuration settings."""
    active_provider_id: uuid.UUID
    active_model: str
    fallback_provider_id: Optional[uuid.UUID] = None
    fallback_model: Optional[str] = None
    temperature: float
    max_tokens: int
    version: int
    active_provider_name: Optional[str] = None
    active_provider_type: Optional[str] = None
    fallback_provider_name: Optional[str] = None
    fallback_provider_type: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class LLMSettingsUpdate(BaseModel):
    """Admin request to change active/fallback LLM providers and generation parameters."""
    active_provider_id: uuid.UUID
    active_model: str = Field(..., min_length=1)
    fallback_provider_id: Optional[uuid.UUID] = None
    fallback_model: Optional[str] = None
    temperature: float = Field(0.0, ge=0.0, le=2.0)
    max_tokens: int = Field(1024, gt=0, le=32768)


