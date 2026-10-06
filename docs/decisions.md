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
---

## 2026-10-05: Phase 3 - Hybrid Retrieval, Reranking, and Layer 1 Fallback

### D-014: Qdrant v1.11.0 Universal Query API for Hybrid Search with Reciprocal Rank Fusion (RRF)
- **Decision:** Upgraded Qdrant to `v1.11.0` to leverage the native Universal Query API (`query_points` with `prefetch` and `models.FusionQuery(fusion=models.Fusion.RRF)`). Prefetches top $K$ candidates for both dense vectors (1024-dim) and sparse BM25 vectors simultaneously under strict `is_active == True` boolean filtering, and fuses ranks using RRF ($k=60$). A resilient client-side RRF fallback is also retained in code for compatibility.
- **Rationale:** Minimizes network round trips by executing dense search, sparse keyword search, payload filtering, and rank fusion within a single declarative database query.
- **Traceability:** Architecture §6.3, Prompt 3.

### D-015: Singleton Cross-Encoder Reranking with FastEmbed ONNX
- **Decision:** Load the cross-encoder model once as a thread-safe singleton (`CrossEncoderSingleton`). Map `settings.RERANKER_MODEL` (`BAAI/bge-reranker-v2-m3`) to FastEmbed's ONNX model `BAAI/bge-reranker-base`. Rerank hybrid candidates and retain top `RERANK_TOP_N` (default 4) for prompt context assembly.
- **Rationale:** Avoids re-initializing heavy ONNX sessions per query while preserving high semantic ranking quality without PyTorch GPU dependencies.
- **Traceability:** Architecture §6.4, Prompt 3.

### D-016: Sigmoid-Normalized Scoring with Raw Logit Telemetry and Layer 1 Fallback Gating
- **Decision:** Apply stable sigmoid normalization $\sigma(s) = \frac{1}{1 + e^{-s}}$ to cross-encoder raw logits to yield scores in $[0, 1]$, where neutral relevance ($s = 0$) maps cleanly to $0.5$, matching `settings.RERANK_THRESHOLD = 0.5`. Both the normalized score and raw logit are tracked in telemetry. If the top score is below `RERANK_THRESHOLD` or no candidates are retrieved, Layer 1 immediately halts the pipeline and returns a structured fallback response.
- **Rationale:** Prevents ungrounded hallucination early in the pipeline without spending expensive generation tokens on queries outside the knowledge base.
- **Traceability:** Architecture §6.4, §6.7, Prompt 3.---

## 2026-10-06: Phase 4 (First Half) - Router, Memory, Canned Replies, Session Management

### D-017: Dynamic KB_TOPIC Configuration and Formatted Greeting Message
- **Decision:** Introduce `KB_TOPIC` (default: `"the knowledge base"`) in `app/core/config.py` and `.env.example`. Update the configuration validator to automatically format `GREETING_MESSAGE` with `KB_TOPIC` (replacing either `{KB_TOPIC}` or `[KB topic]`) when not explicitly customized.
- **Rationale:** Gives deployments an effortless, single-setting method to tailor chatbot scope and personality without hardcoding prompts across services.
- **Traceability:** Architecture §6.2, §12, Prompt 4.

### D-018: Redis Session Management with Sliding TTL and Resilience to Redis Outages
- **Decision:** Implement `SessionManager` storing messages in Redis lists (`session:{user_id}:{session_id}`) trimmed to `HISTORY_MESSAGES` with `LTRIM`, tracked in a per-user sorted set (`user_sessions:{user_id}`) with timestamps, and refreshed with sliding TTL (`SESSION_TTL_HOURS`) on every interaction. If Redis is unavailable or raises connection errors, log warnings and fail gracefully without crashing or failing user requests.
- **Rationale:** Ensures privacy, user isolation, bounded memory footprints, and high availability even when Redis is down.
- **Traceability:** Architecture §5, §8, Prompt 4.

### D-019: Fast Intent Router with JSON Schema Validation, Single Retry, and Fail-Open SEARCH
- **Decision:** Implement `IntentRouter` using the FAST LLM role (`gemini-3.1-flash-lite`), enforcing strict JSON schema `{intent, clarification_message, standalone_query}` via Pydantic. If JSON parsing fails, perform a single immediate correction prompt retry. If parsing still fails or an unhandled LLM error occurs, fail-open to `intent="search"` with the user's raw message. Pure greetings return `GREETING_MESSAGE` with zero retrieval or generation costs; ambiguous inputs ask for clarification; and follow-up queries with coreferences (e.g. "what is its role?") are rewritten into self-contained search queries using recent conversation history while strictly excluding prior fallback/out-of-domain messages.
- **Rationale:** Minimizes latency and token costs on conversational niceties while ensuring conversational queries never fail or block the user when classification is uncertain.
- **Traceability:** Architecture §6.1, §6.2, Prompt 4.

---

## 2026-10-06: Phase 4 (Second Half) - Generation, Layer 2/3 Guardrails, SSE Streaming & Telemetry

### D-020: Layer 2 Stream Buffering for `[[NOT_FOUND]]` Sentinel Detection
- **Decision:** Buffer the first ~15 characters of the LLM generation stream before yielding tokens to the client. If the buffer matches `[[NOT_FOUND]]` (even when split across arbitrary stream chunk boundaries, e.g. `["[[", "NOT_", "FOUND]]"]`), immediately abort the generation stream, suppress all generated tokens, and deliver `FALLBACK_MESSAGE` with `fallback_layer=2`.
- **Rationale:** Prevents models that acknowledge lack of knowledge from leaking sentinel syntax or partial non-answers to the user, while adding negligible (~1 token) time-to-first-token latency.
- **Traceability:** Architecture §6.5, Prompt 4.

### D-021: Layer 3 Citation Verification, Retraction, and Hallucination Filtering
- **Decision:** Post-process generated answers by extracting `\[C(\d+)\]` tags and matching against the injected context chunks ($1 \le n \le N$). Prune any hallucinated tags not in context. If no valid citations remain, emit an SSE `retract` event with `FALLBACK_MESSAGE` (`fallback_layer=3`), instructing the client to replace the displayed text.
- **Rationale:** Ensures that even if an LLM hallucinates an answer or cites non-existent sources, the system strictly retracts ungrounded assertions before concluding the interaction.
- **Traceability:** Architecture §6.6, Prompt 4.

### D-022: Server-Sent Events (SSE) Streaming Protocol and Telemetry Audit Logging
- **Decision:** Implement `POST /api/v1/chat/stream` using HTTP `text/event-stream` with typed events (`token`, `citations`, `retract`, `error`, `done`). Asynchronously insert a record into the `query_logs` table for every turn, recording original and standalone queries, intent, top scores, threshold, fallback layer, cited chunk IDs, and per-stage latencies (router, retrieval, rerank, generation).
- **Rationale:** Complies with Architecture §6.8 SSE streaming protocol and §10 telemetry requirements for end-to-end observability and prompt evaluation.
- **Traceability:** Architecture §6.8, §7, §10, Prompt 4.

---

## 2026-10-06: Phase 5 (First Half) - Frontend Architecture, Auth & Real-Time Chat

### D-023: Next.js Standalone Container Packaging and Fetch-Based SSE Streaming
- **Decision:** Deploy Next.js 14 App Router with `output: 'standalone'` in a multi-stage Alpine Node container (`Dockerfile`). In `streamChat.ts`, implement streaming using `fetch` with `ReadableStream` instead of the browser's native `EventSource`.
- **Rationale:** Native `EventSource` cannot send custom headers (such as `Authorization: Bearer <token>`). Fetch-based streaming allows passing Bearer JWT tokens securely while processing real-time SSE chunks (`token`, `citations`, `retract`, `error`, `done`). Standalone Next.js packaging drastically reduces container footprint and cold-start latency.
- **Traceability:** Architecture §2, §6.8, §11, Prompt 5.

### D-024: Proactive and Reactive JWT Token Refresh with Role-Aware Route Protection
- **Decision:** Store access and refresh tokens with expiration timestamps. Refresh proactively if access token expires within 60 seconds, and refresh reactively if any request receives HTTP 401. Resolve roles via `GET /api/v1/auth/me`. Guard `/` to redirect unauthenticated users to `/login`.
- **Rationale:** Prevents user interruptions during active conversations when short-lived access tokens (30m) expire, while strictly protecting user sessions and displaying role badges.
- **Traceability:** Architecture §8, §9.1, §11, Prompt 5.

---

## 2026-10-06: Phase 5 (Second Half) - Admin Document Manager & Access Isolation

### D-025: Admin Document Manager with Status Polling and Role-Based Access Isolation
- **Decision:** Implement `AdminDocManager.tsx` and protected `/admin` route. Enable file uploads (`.pdf`, `.docx`, `.md`, `.txt`) and web URL ingestion. Poll document status dynamically (every 2.5s) while any document is in progress (`pending`, `processing`, `updating`, `deleting`), auto-stopping on terminal states. Enforce strict role-based access isolation: unauthenticated requests redirect to `/login`, and authenticated non-admin accounts (`role === 'user'`) receive a dedicated 403 Forbidden screen preventing any document operations.
- **Rationale:** Ensures complete document lifecycle management with real-time feedback without overloading the server with indefinite polling, while guaranteeing non-admin users cannot inspect, modify, or delete knowledge base sources.
- **Traceability:** Architecture §5, §8, §9.1, §11, Prompt 5.


