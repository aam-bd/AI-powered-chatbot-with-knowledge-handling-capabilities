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
    models: List[str] = Field(default_factory=list, description="List of supported model identifiers")
    default_model: Optional[str] = Field(None, max_length=100)
    is_enabled: bool = True
    preset_key: Optional[str] = None
    discovery_kind: Optional[str] = "openai_models"

    @model_validator(mode="after")
    def validate_models(self) -> "LLMProviderCreate":
        if self.default_model and self.models and self.default_model not in self.models:
            raise ValueError(f"default_model '{self.default_model}' must be in models list: {self.models}")
        return self


class LLMProviderUpdate(BaseModel):
    """Admin request to update an existing LLM provider."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    base_url: Optional[str] = Field(None, min_length=1, max_length=500)
    api_key: Optional[str] = Field(None, description="New API key (replaces existing if sent)")
    clear_api_key: Optional[bool] = Field(False, description="Explicitly remove stored API key")
    models: Optional[List[str]] = None
    default_model: Optional[str] = Field(None, min_length=1, max_length=100)
    is_enabled: Optional[bool] = None
    discovery_kind: Optional[str] = None

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
    is_preset: bool = False
    preset_key: Optional[str] = None
    docs_url: Optional[str] = None
    key_required: bool = True
    discovery_kind: str = "openai_models"
    discovered_at: Optional[datetime] = None
    discovered_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class ProviderModelRead(BaseModel):
    """Model in the provider's discovered/manual catalog."""
    id: uuid.UUID
    provider_id: uuid.UUID
    model_id: str
    display_name: Optional[str] = None
    context_length: Optional[int] = None
    max_output_tokens: Optional[int] = None
    price_prompt_per_1m: Optional[float] = None
    price_completion_per_1m: Optional[float] = None
    source: str  # 'discovered' | 'manual'
    is_available: bool
    is_enabled: bool
    discovered_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProviderModelUpdate(BaseModel):
    """Admin update to model enablement or manual price override."""
    is_enabled: Optional[bool] = None
    price_prompt_per_1m: Optional[float] = Field(None, ge=0.0)
    price_completion_per_1m: Optional[float] = Field(None, ge=0.0)


class ManualModelCreate(BaseModel):
    """Admin manual model entry when discovery fails."""
    model_id: str = Field(..., min_length=1, max_length=150)
    display_name: Optional[str] = Field(None, max_length=255)
    context_length: Optional[int] = Field(None, gt=0)
    max_output_tokens: Optional[int] = Field(None, gt=0)
    price_prompt_per_1m: Optional[float] = Field(None, ge=0.0)
    price_completion_per_1m: Optional[float] = Field(None, ge=0.0)


class DiscoveredModelRead(BaseModel):
    """Model shape normalized from upstream discovery APIs."""
    model_id: str
    display_name: Optional[str] = None
    context_length: Optional[int] = None
    max_output_tokens: Optional[int] = None
    price_prompt_per_1m: Optional[float] = None
    price_completion_per_1m: Optional[float] = None


class DiscoverUnsavedRequest(BaseModel):
    """One-off discovery probe without persisting keys."""
    provider_type: str = "openai_compatible"
    base_url: str = Field(..., min_length=1, max_length=500)
    api_key: Optional[str] = None
    discovery_kind: str = "openai_models"


class LLMUsageSummaryItem(BaseModel):
    """Aggregated usage metrics per model/provider."""
    provider_id: Optional[uuid.UUID] = None
    provider_name: Optional[str] = None
    model_id: str
    total_requests: int
    total_prompt_tokens: Optional[int] = None
    total_completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    total_errors: int
    avg_latency_ms: float
    estimated_cost: Optional[float] = None
    cost_reason: Optional[str] = None


class LLMUsageResponse(BaseModel):
    """Aggregated usage statistics across a time range."""
    range: str  # '24h' | '7d' | '30d'
    total_requests: int
    total_prompt_tokens: Optional[int] = None
    total_completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    total_errors: int
    avg_latency_ms: float
    total_estimated_cost: Optional[float] = None
    items: List[LLMUsageSummaryItem]


class LLMProviderTestResponse(BaseModel):
    """Response payload for provider test connection endpoint."""
    success: bool
    status: str
    message: str
    sanitized_error: Optional[str] = None
    discovered_count: Optional[int] = None


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


# ==============================================================================
# Prompt 7e-3: System Overview, Health, Routes, Architecture & Runtime Settings
# ==============================================================================

class SystemSettingsResponse(BaseModel):
    """Runtime editable system parameters."""
    reranker_threshold: float
    retrieval_top_k: int
    rerank_top_n: int
    history_messages: int
    rate_limit_per_minute: int
    rate_limit_login_per_minute: int
    sse_keepalive_interval: int
    max_upload_size_bytes: int
    version: int
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SystemSettingsUpdate(BaseModel):
    """Request to update editable system settings."""
    reranker_threshold: Optional[float] = Field(None, ge=0.20, le=0.95)
    retrieval_top_k: Optional[int] = Field(None, ge=5, le=50)
    rerank_top_n: Optional[int] = Field(None, ge=1, le=10)
    history_messages: Optional[int] = Field(None, ge=0, le=20)
    rate_limit_per_minute: Optional[int] = Field(None, ge=10, le=300)
    rate_limit_login_per_minute: Optional[int] = Field(None, ge=2, le=30)
    sse_keepalive_interval: Optional[int] = Field(None, ge=5, le=60)
    max_upload_size_bytes: Optional[int] = Field(None, ge=1048576, le=52428800)

    @model_validator(mode="after")
    def validate_invariants(self) -> "SystemSettingsUpdate":
        if self.retrieval_top_k is not None and self.rerank_top_n is not None:
            if self.rerank_top_n > self.retrieval_top_k:
                raise ValueError("rerank_top_n cannot exceed retrieval_top_k")
        return self


class DependencyHealthItem(BaseModel):
    """Health item for a single system dependency."""
    name: str
    status: str  # 'healthy' | 'degraded' | 'unhealthy'
    latency_ms: Optional[float] = None
    message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class AdminSystemHealthResponse(BaseModel):
    """Comprehensive system health with latencies per dependency."""
    status: str  # 'healthy' | 'degraded' | 'unhealthy'
    version: str
    checked_at: datetime
    dependencies: Dict[str, DependencyHealthItem]


class RouteInfoItem(BaseModel):
    """Registered API route descriptor."""
    method: str
    path: str
    tags: List[str] = []
    summary: Optional[str] = None
    auth_level: str  # 'admin' | 'user' | 'public'


class SystemRoutesResponse(BaseModel):
    """API endpoints introspection response."""
    base_url: str
    docs_url: str
    redoc_url: str
    openapi_url: str
    health_url: str
    routes: List[RouteInfoItem]


class VectorStoreStatsResponse(BaseModel):
    """Vector database and collection statistics."""
    collection_name: str
    status: str
    points_count: int
    vectors_count: int
    segments_count: int
    disk_data_size_bytes: Optional[int] = None
    dense_dim: int
    has_sparse: bool
    indexed_documents_count: int
    active_versions_count: int
    superseded_versions_count: int


class ArchitectureOverviewResponse(BaseModel):
    """Live retrieval and ranking architecture details."""
    dense_model: str
    dense_dim: int
    sparse_model: str
    fusion_method: str
    rrf_k: int
    retrieval_top_k: int
    reranker_model: str
    reranker_threshold: float
    rerank_top_n: int
    chunk_size: int
    chunk_overlap: int
    history_window: int
    guardrail_layers: List[str]
    fallback_message: str


class WorkerStatsResponse(BaseModel):
    """Celery worker and task queue telemetry."""
    online_workers_count: int
    worker_names: List[str]
    active_tasks_count: int
    queue_length: int
    last_beat_run: Optional[datetime] = None
    last_reconciler_run: Optional[datetime] = None
    reconciler_fixed_count: int = 0
    reconciler_last_status: Optional[str] = None
    failed_ingestions_count: int = 0


class ChatQualityIndicatorsResponse(BaseModel):
    """Chat quality and grounding metrics."""
    window: str  # '24h' | '7d'
    total_queries: int
    fallback_count: int
    fallback_rate: float
    layer1_fallback_count: int
    layer2_fallback_count: int
    layer3_fallback_count: int
    avg_retrieval_score: Optional[float] = None
    queries_with_no_sources: int


class AuditLogEntryResponse(BaseModel):
    """Admin audit log entry."""
    id: uuid.UUID
    created_at: datetime
    user_id: Optional[uuid.UUID] = None
    user_email: Optional[str] = None
    action: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    details: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class RecentActivityResponse(BaseModel):
    """Recent admin audit trails and system errors."""
    audit_logs: List[AuditLogEntryResponse]
    recent_errors: List[Dict[str, Any]]


class EnvironmentSettingItem(BaseModel):
    """Allowlisted non-secret configuration item."""
    key: str
    value: str
    description: Optional[str] = None


class SystemEnvironmentResponse(BaseModel):
    """Allowlisted system environment variables."""
    settings: List[EnvironmentSettingItem]



