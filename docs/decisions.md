# Design Decisions Log

This document records key architectural and design decisions made throughout development, with their rationale and context.

---

## 2026-10-05: Phase 0 - Foundation Architecture

### D-001: Pydantic Settings for Single Source of Truth
- **Decision:** Use `pydantic-settings` to manage all configuration parameters in `app/core/config.py`.
- **Rationale:** Strongly-typed configuration with automatic environment variable parsing, default fallback handling, and secret masking (`SecretStr`).
- **Traceability:** Architecture §12.

### D-002: Deferred LLM Validation
- **Decision:** Do not fail application startup if `LLM_API_KEY`, `FAST_MODEL`, or `ANSWER_MODEL` are missing. Only enforce these when LLM operations are invoked.
- **Rationale:** Allows non-LLM services, health probes, migrations, and local tests to run without requiring active LLM credentials.
- **Traceability:** Architecture §6.9, §12.

### D-003: Structured JSON Logging with Request Tracing
- **Decision:** Standardize on Loguru with JSON formatting to both stdout and rotating file (`logs/app.log`, 10MB limit, 14-day retention).
- **Rationale:** Provides consistent observability, parseable logs for automated analysis, and tracing through `X-Request-ID`.
- **Traceability:** Architecture §10.

### D-004: Health Check Behavior
- **Decision:** `GET /api/v1/health` checks PostgreSQL, Redis, and Qdrant connectivity and reports whether LLM is configured without making outbound paid LLM calls.
- **Rationale:** Avoids ongoing costs, external latency, and false degradation during third-party provider outages while preserving accurate dependency telemetry.
- **Traceability:** Architecture §8, §10.

---

## 2026-10-05: Phase 1 - Database and Authentication

### D-005: Argon2 Password Hashing & Strict Role-Based RBAC
- **Decision:** Use Argon2 (`argon2-cffi`) for all user password hashing, and hardcode `role = "user"` during self-registration (`POST /auth/register`).
- **Rationale:** Protects against GPU cracking attacks. Strictly prevents privilege escalation attacks by requiring administrative accounts to be seeded via CLI script or environment variables.
- **Traceability:** Architecture §9.1, §9.4.

### D-006: Partial Unique Index on Document SHA-256
- **Decision:** Define partial unique index `ix_documents_sha256_active` on `documents(sha256)` WHERE `status != 'deleting'`.
- **Rationale:** Prevents duplicate ingestion of identical files among active/pending documents while permitting clean re-ingestion after a document is marked for deletion.
- **Traceability:** Architecture §4.1.

### D-007: Standardized Error Response Format & Redis Rate Limiting
- **Decision:** Enforce uniform JSON error payload `{"detail": "...", "code": "..."}` across all HTTP exception handlers and apply Redis-backed sliding window rate limiting (5 req/min on `/auth/login`, 60 req/min general) with graceful in-memory fallback on Redis unavailability.
- **Rationale:** Ensures consistent API contract for frontend/clients and defends against credential stuffing and brute-force attacks.
- **Traceability:** Architecture §8, §9.3.

---

## 2026-10-05: Phase 1.5 - LLM Provider Layer

### D-008: Provider-Agnostic LLM Abstraction with Normalized Errors and Role Overrides
- **Decision:** Implement `app/services/llm/` with `OpenAICompatAdapter` and `AnthropicAdapter` under an abstract `LLMAdapter` interface, normalizing all provider exceptions to `LLMAuthError`, `LLMRateLimitError`, `LLMTimeoutError`, and `LLMUnavailableError`. System prompts are placed according to provider expectations (prepended to messages for OpenAI-compatible, top-level `system` parameter for Anthropic). Exponential backoff retries (1s, 2s) are handled explicitly up to `LLM_MAX_RETRIES`.
- **Rationale:** Decouples core business logic (intent router and RAG engine) from vendor-specific SDK quirks and enables zero-code provider switching via configuration.
- **Traceability:** Architecture §6.9, §12.

### D-009: Google AI Studio Free Tier Model Selection
- **Decision:** Selected `gemini-3.1-flash-lite` as the active model for Google AI Studio Free Tier OpenAI-compatible endpoint.
- **Rationale:** Live API probes against the Google AI Studio Free Tier API key verified that legacy models (`gemini-2.0-flash`, `gemini-1.5-flash`) are retired on modern endpoints, while `gemini-3.8-flash` experiences transient capacity spikes (HTTP 503). `gemini-3.1-flash-lite` provides rapid token generation, low latency, and zero capacity throttle errors under free tier rate limits.
- **Traceability:** Architecture §6.9, §12.

---

## 2026-10-05: Phase 2 - Embeddings, Ingestion, and Document Lifecycle

### D-010: CPU-Optimized Dual Dense & BM25 Sparse Embedding via FastEmbed
- **Decision:** Implement `LocalEmbeddingService` using FastEmbed's ONNX CPU runtime without PyTorch or CUDA dependencies. Map `BAAI/bge-m3` to FastEmbed's 1024-dimensional ONNX model `BAAI/bge-large-en-v1.5` while preserving `BAAI/bge-m3` as the collection metadata contract for Qdrant Embedding Guard. Sparse representations use `Qdrant/bm25` indices and weights.
- **Rationale:** Eliminates gigabytes of PyTorch GPU bloat and provides fast, predictable vector generation on standard CPU server instances.
- **Traceability:** Architecture §4.3, §4.4, §12.

### D-011: Blue-Green Ingestion Cutover with Qdrant Boolean Index
- **Decision:** During document ingestion and version updates, all new chunks are upserted into Qdrant collection `kb_chunks` with `is_active=False`. Only after the entire document has been parsed, chunked, and embedded without error does a single payload update flip `is_active=True` for the target version, followed by purging chunks of the previous version. If ingestion fails, unactivated chunks are purged and the active version remains completely unaffected.
- **Rationale:** Guarantees search consistency (zero partial-state visibility) and zero-downtime document updates.
- **Traceability:** Architecture §4.2, §4.5.

### D-012: Comprehensive Defense-in-Depth SSRF Protection on Web Ingestion
- **Decision:** Multi-layered defense on `parse_web_url`: enforces HTTP/HTTPS scheme, matches domain against `ALLOWED_URL_DOMAINS` allowlist, resolves DNS hostnames and verifies all resolved IP addresses are neither loopback (`127.0.0.0/8`, `::1`), private (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), link-local (`169.254.0.0/16`), multicast, nor reserved. Follows redirects manually with re-validation at every hop, and enforces maximum content-length size caps and request timeouts.
- **Rationale:** Completely eliminates Server-Side Request Forgery (SSRF) vulnerabilities against internal network services, Docker host APIs, and cloud provider metadata endpoints (e.g., AWS/GCP 169.254.169.254).
- **Traceability:** Architecture §9.3.

### D-013: Deterministic UUIDv5 Point IDs and Two-Phase Deletion Lifecycle
- **Decision:** Generate deterministic RFC 4122 UUID v5 point IDs using `uuid.uuid5(uuid.NAMESPACE_URL, f"{document_id}:{version}:{chunk_index}")`. Deletion is implemented in two phases: Phase 1 (synchronous HTTP DELETE) marks the document `status='deleting'` and immediately flips Qdrant `is_active=False` so it disappears instantly from all queries; Phase 2 (asynchronous Celery worker task) purges all vector points from Qdrant, deletes the local file from storage, and removes the PostgreSQL document record.
- **Rationale:** Ensures strict Qdrant point ID compatibility, enforces task idempotency across re-runs, and provides instant query response times for user deletions.
- **Traceability:** Architecture §4.1, §4.2, §4.3.


