# Progress Log
Read this and docs/architecture.md at the start of every task. Update this file at the end of every task.

## Current status
- Current phase: 1 (database and authentication)
- Last completed task: Prompt 0: Scaffold, config, logging, health
- Next task: Prompt 1: Database and authentication

## Phase checklist
- [x] 0 Scaffold, config, logging, /health
- [ ] 1 DB models, migrations, auth, rate limiting
- [ ] 1.5 LLM provider layer (OpenAI-compatible and Anthropic adapters)
- [ ] 2 Embeddings, parsers, ingestion, document lifecycle
- [ ] 3 Hybrid retrieval, rerank, Layer 1 fallback
- [ ] 4 Router, memory, generation, citations, SSE chat
- [ ] 5 Frontend (login, chat, admin)
- [ ] 6 Evaluation and threshold calibration
- [ ] 7 Audit, hardening, README

## Requirements status (from architecture §1.1)
C1 [ ]  C2 [ ]  C3 [ ]  G1 [ ]  G2 [ ]  G3 [ ]  G4 [ ]
G5 [ ]  G6 [x]  G7 [x]  S1 [ ]  S2 [ ]  S3 [ ]

## Decisions and deviations from architecture.md
- 2026-10-05: Added `greenlet>=3.0.0` to `requirements.txt` to support SQLAlchemy 2 async engine with `asyncpg`.
- 2026-10-05: Used bash `/dev/tcp` TCP handshake check for Qdrant healthcheck in `docker-compose.yml` because the official `qdrant/qdrant:v1.9.0` image does not bundle `curl`.

## Known issues / TODO
- None from Phase 0.

## Session log (newest first)
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