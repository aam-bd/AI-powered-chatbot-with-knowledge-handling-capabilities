# Progress Log
Read this and docs/architecture.md at the start of every task. Update this file at the end of every task.

## Current status
- Current phase: 1.5 (LLM provider layer)
- Last completed task: Prompt 1: Database and authentication
- Next task: Prompt 1.5: LLM provider layer

## Phase checklist
- [x] 0 Scaffold, config, logging, /health
- [x] 1 DB models, migrations, auth, rate limiting
- [ ] 1.5 LLM provider layer (OpenAI-compatible and Anthropic adapters)
- [ ] 2 Embeddings, parsers, ingestion, document lifecycle
- [ ] 3 Hybrid retrieval, rerank, Layer 1 fallback
- [ ] 4 Router, memory, generation, citations, SSE chat
- [ ] 5 Frontend (login, chat, admin)
- [ ] 6 Evaluation and threshold calibration
- [ ] 7 Audit, hardening, README

## Requirements status (from architecture §1.1)
C1 [ ]  C2 [ ]  C3 [ ]  G1 [ ]  G2 [ ]  G3 [ ]  G4 [ ]
G5 [ ]  G6 [x]  G7 [x]  S1 [ ]  S2 [x]  S3 [ ]

## Decisions and deviations from architecture.md
- 2026-10-05: Added `pyjwt[crypto]>=2.8.0`, `argon2-cffi>=23.1.0`, and `email-validator>=2.0.0` to `requirements.txt` for Argon2 hashing, JWT access/refresh token cryptography, and email validation.
- 2026-10-05: Configured `NullPool` for SQLAlchemy async engine in test fixtures to prevent cross-event-loop task binding during synchronous `TestClient` executions.
- 2026-10-05: Added `greenlet>=3.0.0` to `requirements.txt` to support SQLAlchemy 2 async engine with `asyncpg`.
- 2026-10-05: Used bash `/dev/tcp` TCP handshake check for Qdrant healthcheck in `docker-compose.yml` because the official `qdrant/qdrant:v1.9.0` image does not bundle `curl`.

## Known issues / TODO
- None from Phase 1.

## Session log (newest first)
### 2026-10-05, Phase 1 (Database and Authentication)
- Done:
  - Implemented SQLAlchemy 2 database models in `app/models/sql_models.py` (`User`, `Document` with partial unique index on `sha256` where `status != 'deleting'`, `QueryLog`).
  - Configured Alembic with `alembic.ini` and `app/db/migrations/env.py`, generated and executed initial migration `001_initial_schema.py` against PostgreSQL.
  - Implemented Pydantic models in `app/models/schemas.py` for user registration, login, token refresh, user responses, and standardized error responses `{detail, code}`.
  - Implemented security utilities in `app/core/security.py`: Argon2 password hashing/verification, HS256 JWT access (30m) & refresh (7d) tokens, and FastAPI dependencies `get_current_user`, `require_user`, and `require_admin`.
  - Implemented sliding-window rate limiting in `app/core/rate_limit.py` using Redis with in-memory fallback. Applied strict 5 req/min on `/auth/login` and 60 req/min general limit.
  - Implemented authentication endpoints in `app/api/v1/auth.py`: `POST /register` (hardcoded role="user"), `POST /login`, `POST /refresh`, `GET /me`, and test admin route `GET /admin-only`.
  - Standardized error handling in `app/main.py` ensuring uniform `{detail, code}` structure and status codes across HTTP exceptions and validation errors.
  - Created admin seeding script in `scripts/seed_admin.py` with idempotent role and password management, and startup execution when `ADMIN_EMAIL` and `ADMIN_PASSWORD` are configured.
  - Created comprehensive test suite in `tests/test_auth.py` covering registration privilege boundaries, duplicate registration rejection, password verification, refresh token lifecycle, expired/invalid tokens, admin vs user RBAC, login rate limiting, and partial unique index on document sha256.
- Tests run and results:
  - `docker compose exec api pytest tests/ -v`: All 17 tests passed (8 auth tests, 5 config tests, 4 health tests).
  - Manual live verification of `POST /auth/register`: 201 Created with role `"user"`.
  - Manual live verification of duplicate `POST /auth/register`: 409 Conflict with code `"EMAIL_ALREADY_REGISTERED"`.
  - Manual live verification of `POST /auth/login`: 200 OK returning access and refresh JWTs; invalid password returned 401 with code `"INVALID_CREDENTIALS"`.
  - Manual live verification of `POST /auth/refresh`: 200 OK returning refreshed access token.
  - Manual live verification of `GET /auth/me`: 200 OK with authenticated user profile.
  - Manual live verification of `GET /auth/admin-only`: 200 OK for admin; 403 Forbidden with code `"FORBIDDEN"` for normal user.
  - Manual live verification of rate limiting on `POST /auth/login`: 6th request returned 429 Too Many Requests with code `"RATE_LIMIT_EXCEEDED"`.
  - Verified database schema and tables via `psql` in PostgreSQL container.
- Files changed:
  - `backend/requirements.txt`
  - `backend/alembic.ini`
  - `backend/app/db/migrations/env.py`
  - `backend/app/db/migrations/script.py.mako`
  - `backend/app/db/migrations/versions/001_initial_schema.py`
  - `backend/app/models/sql_models.py`
  - `backend/app/models/schemas.py`
  - `backend/app/core/security.py`
  - `backend/app/core/rate_limit.py`
  - `backend/app/api/v1/auth.py`
  - `backend/app/main.py`
  - `backend/app/db/session.py`
  - `backend/scripts/seed_admin.py`
  - `backend/tests/conftest.py`
  - `backend/tests/test_auth.py`
  - `docs/decisions.md`
  - `docs/progress.md`
### 2026-10-05, Phase 0
- Done:
  - Created complete monorepo skeleton matching architecture §15 with placeholders for backend, frontend, scripts, and evaluation suites.
  - Implemented `app/core/config.py` using `pydantic-settings` including every setting from architecture §12, secret masking with `SecretStr`, and deferred LLM credential validation.
  - Implemented `app/core/logger.py` with Loguru structured JSON logging to stdout and rotating file `logs/app.log` (10MB, 14 days retention), plus `RequestIdMiddleware` for request ID propagation in headers and log lines.
  - Implemented `GET /api/v1/health` reporting status of PostgreSQL, Redis, Qdrant, and whether LLM is configured without making external paid calls.
  - Configured `docker-compose.yml` with services (`api`, `worker`, `beat`, `frontend`, `postgres`, `redis`, `qdrant`), named volumes (`postgres_data`, `qdrant_data`, `uploads`, `model_cache`), and healthchecks.
  - Created `.env.example` with documented presets for OpenAI, OpenRouter, Gemini, and Anthropic.
  - Created `Makefile` with targets `up`, `down`, `logs`, `test`, `eval`, `lint`.
  - Added `logs/` to `.gitignore`.
- Tests run and results:
  - `docker compose ps`: All 7 services healthy.
  - `curl -i http://localhost:8000/api/v1/health`: HTTP 200, `X-Request-ID` present, all dependencies reported healthy.
  - `/docs` and `/redoc`: HTTP 200 OK.
  - `logs/app.log`: verified valid JSON formatting with request ID tracing.
  - Invalid setting test (`CHUNK_SIZE_TOKENS=-5`): cleanly raised `pydantic_core.ValidationError` with descriptive message.
  - `pytest tests/ -v`: 9 passed in 0.22s.
- Files changed:
  - `docker-compose.yml`
  - `Makefile`
  - `.env.example`
  - `.gitignore`
  - `README.md`
  - `docs/decisions.md`
  - `docs/progress.md`
  - `backend/requirements.txt`
  - `backend/Dockerfile`
  - `backend/app/main.py`
  - `backend/app/api/router.py`
  - `backend/app/api/v1/health.py`
  - `backend/app/api/v1/auth.py`
  - `backend/app/api/v1/chat.py`
  - `backend/app/api/v1/documents.py`
  - `backend/app/core/config.py`
  - `backend/app/core/logger.py`
  - `backend/app/core/security.py`
  - `backend/app/core/rate_limit.py`
  - `backend/app/db/session.py`
  - `backend/app/db/redis.py`
  - `backend/app/db/qdrant.py`
  - `backend/app/models/sql_models.py`
  - `backend/app/models/schemas.py`
  - `backend/app/services/llm/base.py`
  - `backend/app/services/llm/openai_compat.py`
  - `backend/app/services/llm/anthropic.py`
  - `backend/app/services/llm/factory.py`
  - `backend/app/services/intent_router.py`
  - `backend/app/services/rag_engine.py`
  - `backend/app/services/citation_service.py`
  - `backend/app/services/session_manager.py`
  - `backend/app/services/parsers/pdf.py`
  - `backend/app/services/parsers/docx.py`
  - `backend/app/services/parsers/markdown.py`
  - `backend/app/services/parsers/text.py`
  - `backend/app/services/parsers/web.py`
  - `backend/app/workers/celery_app.py`
  - `backend/app/workers/tasks_ingestion.py`
  - `backend/app/workers/tasks_deletion.py`
  - `backend/app/workers/tasks_reconcile.py`
  - `backend/scripts/seed_admin.py`
  - `backend/scripts/search.py`
  - `backend/scripts/reindex.py`
  - `backend/eval/calibration_set.json`
  - `backend/eval/test_set.json`
  - `backend/eval/calibrate_threshold.py`
  - `backend/eval/run_eval.py`
  - `backend/tests/conftest.py`
  - `backend/tests/test_config.py`
  - `backend/tests/test_health.py`
  - `frontend/package.json`
  - `frontend/Dockerfile`
  - `frontend/src/components/ChatWindow.tsx`
  - `frontend/src/components/CitationsDrawer.tsx`
  - `frontend/src/components/AdminDocManager.tsx`
  - `frontend/src/components/SessionControls.tsx`
  - `frontend/src/components/LoginForm.tsx`
  - `frontend/src/services/api.ts`
  - `frontend/src/services/streamChat.ts`
- Unfinished / next:
  - Prompt 1: Database models, migrations, auth, and rate limiting.