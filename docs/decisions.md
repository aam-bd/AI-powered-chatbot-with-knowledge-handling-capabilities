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

