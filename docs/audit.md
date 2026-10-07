# System Security, Architecture & Requirements Audit Report (Phase 7a)

**Date:** 2026-10-06  
**Auditor:** Automated System Audit (Prompt 7a)  
**Status:** Comprehensive Audit Complete — Zero Code Changes Made  
**Scope:** Architecture V4 (Sections 1.1, 4.1, 7, 8, 9, 11, 12), Requirements C1–C3, G1–G7, S1–S3, Extensions E1–E3, and Checklists 1–10.

---

## Executive Summary

A comprehensive, zero-code-change audit was conducted across the entire repository to evaluate code quality, requirements traceability, security hardening, test stability, and operational readiness.

### Key Strengths
1. **Flawless Baseline Stability:** The backend automated test suite is exceptionally stable. The entire 75-test suite was executed twice consecutively in Docker (`docker compose exec api pytest tests/ -v`), achieving **100% passing rate** in ~32s with zero failures, zero skipped tests, and zero flaky tests.
2. **Robust RAG Core:** Hybrid search, cross-encoder reranking, and the 3-layer grounding guardrail (Layer 1 rerank threshold gate, Layer 2 sentinel streaming window buffer, Layer 3 citation verification and retract event) are completely implemented and verified by automated tests.
3. **Rigorous File Validation & SSRF Protection:** File uploads strictly enforce magic bytes, file extensions, and size limits. Web URL ingestion features comprehensive SSRF defenses (RFC 1918 private subnets, loopback IPv4/IPv6, AWS/GCP cloud metadata link-local endpoints, and domain allowlists).
4. **Secret-Free Git History:** An exhaustive inspection of git commit history (`git log -S`) and tracked files confirmed that no real API keys, credentials, or private keys have ever been committed.

### Primary Risks & Findings
1. **Critical Demo Credentials & Login Fillers:** A "Fill Demo Admin Credentials" button exists in `frontend/src/components/LoginForm.tsx` prefilling `admin@example.com` and `AdminPassword123!`. This string is compiled directly into the production client bundle. Furthermore, `README.md` documents default credentials, and `backend/app/core/config.py` specifies a default insecure fallback secret for `JWT_SECRET_KEY`.
2. **Missing Architectural Extensions (E1, E2, E3):**
   - **E1 (Chat History Persistence):** Chat memory currently resides exclusively in Redis with a 24-hour TTL. PostgreSQL tables `chat_sessions` and `chat_messages` are not yet created, and past messages cannot be restored across logins or session switches.
   - **E2 (Account & Session Management):** Self-registration UI (`/register`) and password change UI/endpoint (`/auth/change-password`) are missing. Refresh tokens lack token IDs (JTI) and revocation markers in Redis (`revoked:{token_id}`) upon logout. Server-side `PASSWORD_MIN_LENGTH=10` is not yet enforced.
   - **E3 (Admin User Management):** Endpoints `GET /users`, `PATCH /users/{id}`, and the frontend `AdminUsers` tab are not yet implemented.
3. **Missing HTTP Security Headers:** Neither the FastAPI backend nor the Next.js frontend currently sets standard security headers (`Content-Security-Policy`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`).

---

## Prioritized Findings Matrix

| ID | Checklist Area | Severity | File & Location | Summary of Issue | Proposed Fix (Phase) |
|---|---|---|---|---|---|
| **F-01** | 1. Secrets & Credentials | **Critical** | `frontend/src/components/LoginForm.tsx:36-40, 124-132` | "Fill Demo Admin Credentials" helper button hardcodes `admin@example.com` and `AdminPassword123!` into the UI and production bundle. | Remove demo button and prefilled values; render only a clean standard form (Phase 7b). |
| **F-02** | 1. Secrets & Credentials | **Critical** | `README.md:122-125` | README explicitly lists default credentials (`admin@example.com` / `Admin123!@#`). | Remove default credential text; explain that admin credentials originate solely from `.env` (Phase 7b / 7e). |
| **F-03** | 1. Secrets & Credentials | **Critical** | `backend/app/core/config.py:29` | Default fallback `JWT_SECRET_KEY` set to `"default-insecure-secret-key-change-in-production"`. | Remove default insecure secret or fail startup if `APP_ENV != development` (Phase 7b). |
| **F-04** | 1. Secrets & Credentials | **High** | `.env.example:21-22` | Concrete passwords and emails (`admin@example.com`, `adminsecurepassword123`) provided in template. | Replace with generic placeholders (e.g. `admin@yourcompany.com`, `replace_with_min_10_char_password`) (Phase 7b). |
| **F-05** | 2. Authentication Flows | **High** | `backend/app/core/security.py:50-60`, `backend/app/api/v1/auth.py:116-162` | Refresh tokens lack `jti` (JWT ID); no `POST /auth/logout` endpoint; no Redis revocation check (`revoked:{token_id}`). | Add `jti` to refresh token, implement `POST /auth/logout` writing Redis key with token TTL, and verify revocation in `/refresh` (Phase 7b). |
| **F-06** | 2. Authentication Flows | **High** | `frontend/src/context/AuthContext.tsx:81-85` | Frontend `logout()` only clears local storage without invalidating the refresh token on the server. | Update `logout()` to call `POST /auth/logout` before clearing local storage (Phase 7b). |
| **F-07** | 2. Authentication Flows | **High** | `frontend/src/app/` | Missing registration page (`/register`, `RegisterForm.tsx`) and account page (`/account` for password change). | Create `/register` with client validation and link from login; create `/account` page (Phase 7b). |
| **F-08** | 2. Authentication Flows | **High** | `backend/app/core/config.py`, `backend/app/api/v1/auth.py` | Missing `PASSWORD_MIN_LENGTH=10` setting in `config.py` and lack of server-side minimum password length validation. | Add `PASSWORD_MIN_LENGTH: int = 10` to `Settings` and validate on registration and password change (Phase 7b). |
| **F-09** | 2. Authentication Flows | **High** | `backend/app/api/v1/auth.py` | Missing `POST /auth/change-password` endpoint requiring verification of the user's current password. | Implement `POST /auth/change-password` validating current password and hashing new password (Phase 7b). |
| **F-10** | 4. Chat History | **High** | `backend/app/models/sql_models.py`, `backend/app/db/migrations/` | Missing `chat_sessions` and `chat_messages` tables in PostgreSQL. History exists only in Redis with a 24h TTL. | Add Alembic migration `002_chat_history.py` and SQLAlchemy models for persistent sessions and messages (Phase 7c). |
| **F-11** | 4. Chat History | **High** | `backend/app/api/v1/chat.py` | Missing endpoints `GET /chat/sessions/{id}/messages` and `PATCH /chat/sessions/{id}` (rename). | Implement endpoints with owner-only isolation returning 404 for non-owners (Phase 7c). |
| **F-12** | 4. Chat History | **High** | `frontend/src/components/`, `frontend/src/app/page.tsx` | No message restoration on session switch; missing `ChatHistorySidebar.tsx` with conversation rename/delete and persistent reload across logins. | Create `ChatHistorySidebar.tsx`, fetch past messages and citations upon session selection (Phase 7c). |
| **F-13** | 3. Authorization | **High** | `backend/app/api/v1/` | Missing admin user management endpoints: `GET /users` and `PATCH /users/{id}` (role change, activation/deactivation). | Implement user management with last-active-admin protection and self-demotion guards (Phase 7d). |
| **F-14** | 3. Authorization | **High** | `frontend/src/components/` | Missing `AdminUsers` tab on `/admin` for user listing, role modifications, and account deactivations. | Build `AdminUsers.tsx` tab in admin portal (Phase 7d). |
| **F-15** | 6. Security Hardening | **High** | `backend/app/main.py`, `frontend/next.config.mjs` | Missing HTTP security headers (CSP, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`). | Add security headers middleware in FastAPI and headers in `next.config.mjs` (Phase 7b). |
| **F-16** | 8. Dependencies | **Medium** | `docker-compose.yml` (API container) | `pip-audit` identified 2 vulnerabilities in container base `setuptools 79.0.1` (`PYSEC-2026-3447`). | Add `pip install --upgrade setuptools>=83.0.0` in `Dockerfile` (Phase 7b). |
| **F-17** | 8. Dependencies | **Medium** | `frontend/package.json` | `npm audit` flagged vulnerabilities in `next 14.2.0` (DoS, Server Actions) and `postcss` / `braces`. Missing committed `package-lock.json`. | Upgrade Next.js to latest secure 14.x patch release, generate and commit `package-lock.json` (Phase 7b). |
| **F-18** | 9. UX Gaps | **Medium** | `frontend/src/components/ChatWindow.tsx:380-410` | No stop-generation (AbortController) button while streaming; send button is disabled with spinner only. | Implement stream abort handling using `AbortController` (Phase 7c / 7e). |
| **F-19** | 9. UX Gaps | **Medium** | `frontend/src/components/ChatWindow.tsx:200-224` | Assistant answers rendered as plain text (`whitespace-pre-wrap`) with citation regex rather than parsed Markdown. | Integrate a lightweight Markdown renderer supporting lists, bold, italics, and code blocks (Phase 7c). |
| **F-20** | 10. Operations | **Medium** | `docker-compose.yml:107, 134` | Celery worker and beat containers use dummy healthchecks (`python -c 'exit(0)'`) rather than probing Celery status. | Configure `celery -A app.workers.celery_app inspect ping` in container healthchecks (Phase 7e). |
| **F-21** | 10. Operations | **Low** | `backend/app/models/sql_models.py` | `query_logs` table has no automatic partition pruning or retention window. | Add retention policy note in documentation or an optional Celery purge task (Phase 7e). |
| **F-22** | 9. UX Gaps | **Low** | `frontend/src/components/ChatWindow.tsx`, `SessionControls.tsx` | Missing `aria-label` attributes on icon-only interactive buttons; no visible skip-to-content anchor. | Add explicit `aria-label` tags to icon buttons for WCAG 2.1 compliance (Phase 7b / 7c). |

---

## Detailed Checklist Findings

### Checklist 1: Secrets & Demo Credentials
- **Repository Search Results:**
  - `git log -S` check confirmed no real production API keys or credentials exist in git history.
  - `frontend/src/components/LoginForm.tsx:36-40, 124-132`: Contains `handleFillDemoAdmin()` button setting `admin@example.com` and `AdminPassword123!`.
  - **Container Production Bundle:** Inspected running frontend `.next` bundle (`docker compose exec frontend grep -rn "admin@example.com" /app/.next`). Verified that `admin@example.com`, `AdminPassword123!`, and `Fill Demo Admin Credentials` are compiled directly into the client JavaScript bundle.
  - `README.md:122-125`: Contains written instructions listing `admin@example.com` and `Admin123!@#` as default credentials.
  - `backend/app/core/config.py:29`: Contains default fallback `JWT_SECRET_KEY = SecretStr("default-insecure-secret-key-change-in-production")`.
  - `.env.example:21-22`: Uses concrete values `admin@example.com` and `adminsecurepassword123` instead of non-functional placeholders.
- **Severity:** **Critical** (F-01, F-02, F-03), **High** (F-04).
- **Remediation:** Remove the demo button and hardcoded values from `LoginForm.tsx`; update `README.md` to instruct users to create administrator credentials in `.env`; replace `.env.example` values with placeholders; eliminate default fallback for `JWT_SECRET_KEY` in production environments.

### Checklist 2: Authentication Flows
- **User Registration:** `POST /api/v1/auth/register` is implemented in `backend/app/api/v1/auth.py:32-68` and correctly forces `role = "user"` regardless of request payload. However, no `/register` frontend page or `RegisterForm.tsx` component exists.
- **Login Flow:** `POST /api/v1/auth/login` works correctly and enforces rate limits (5 attempts per minute per IP).
- **Token Refresh & Revocation:** `POST /api/v1/auth/refresh` exchanges refresh tokens for new access tokens. However:
  - Tokens lack a unique identifier (`jti`).
  - No `POST /api/v1/auth/logout` endpoint exists.
  - No Redis revocation marker (`revoked:{token_id}`) is stored or checked.
  - Client logout simply discards tokens in `localStorage`, leaving the refresh token valid for 7 days on the server.
- **Password Policy:** Architecture §9.1 and §12 specify `PASSWORD_MIN_LENGTH=10`. This configuration is currently missing from `backend/app/core/config.py` and is not enforced during registration.
- **Password Change:** No `POST /api/v1/auth/change-password` endpoint or account settings UI exists.
- **Severity:** **High** (F-05, F-06, F-07, F-08, F-09).
- **Remediation:** Implement `jti` in JWTs, add `POST /auth/logout` with Redis revocation, create `POST /auth/change-password`, enforce `PASSWORD_MIN_LENGTH=10` server-side, and build `/register` and `/account` pages.

### Checklist 3: Authorization & Route Guards
- **Admin Endpoints:** All administrative document endpoints (`POST /documents`, `PUT /documents/{id}`, `GET /documents`, `GET /documents/{id}/status`, `DELETE /documents/{id}`) in `backend/app/api/v1/documents.py` explicitly depend on `require_admin`.
- **Frontend Route Protection:** `frontend/src/app/admin/page.tsx` checks user profile via `GET /auth/me` and redirects non-admin users with an access denied banner.
- **User Management Authorization:** The required administrative endpoints `GET /users` and `PATCH /users/{id}` (Architecture §8) are missing.
- **Session Ownership:** Session operations (`DELETE /chat/sessions/{id}`) currently enforce owner isolation in Redis (`user_id` in Redis key), returning 404 for unauthorized accesses.
- **Severity:** **High** (F-13, F-14).
- **Remediation:** Implement `GET /users` and `PATCH /users/{id}` with safeguards preventing self-demotion and ensuring at least one active admin remains. Build the `AdminUsers` UI tab.

### Checklist 4: Chat History Persistence
- **Storage Layer Analysis:** Chat messages are currently stored only in Redis via `SessionManager` under `session:{user_id}:{session_id}` with a 24-hour sliding TTL, capped at the last 6 messages (`HISTORY_MESSAGES`).
- **PostgreSQL Persistence:** PostgreSQL tables `chat_sessions` and `chat_messages` (mandated by Architecture §4.1 and §7) do not exist.
- **Session Restoration:** When a user selects a past session in `frontend/src/app/page.tsx`, the messages are not restored because `GET /chat/sessions/{id}/messages` is not implemented.
- **Session Renaming:** `PATCH /chat/sessions/{id}` is not implemented.
- **Multi-user Isolation:** User isolation is preserved in Redis via key prefixing (`session:{user_id}:{session_id}`), but conversation history is entirely lost if Redis restarts or after 24 hours of inactivity.
- **Severity:** **High** (F-10, F-11, F-12).
- **Remediation:** Create Alembic migration for `chat_sessions` and `chat_messages`, store messages in PostgreSQL during streaming, implement message retrieval and rename endpoints, and build `ChatHistorySidebar.tsx`.

### Checklist 5: Requirements Traceability (Architecture §1.1)

| Requirement | Description | Type | Satisfying Files | Satisfying Tests | Audit Status |
|---|---|---|---|---|---|
| **C1** | Trainable on custom medium KB | Core | `app/services/ingestion.py`, `app/db/qdrant.py`, `app/services/parsers/` | `tests/test_lifecycle_consistency.py` | **Satisfied** |
| **C2** | Answers only from KB | Core | `app/services/generation_service.py`, `app/services/citation_service.py` | `tests/test_rag_pipeline.py` | **Satisfied** |
| **C3** | Graceful out-of-scope handling | Core | `app/services/intent_router.py`, `app/services/rag_engine.py` | `tests/test_rag_pipeline.py`, `tests/test_router.py` | **Satisfied** |
| **G1** | Context-aware retrieval | Good | `app/services/intent_router.py`, `app/services/retrieval.py` | `tests/test_router.py`, `tests/test_retrieval.py` | **Satisfied** |
| **G2** | Short-term conversation memory | Good | `app/services/session_manager.py` | `tests/test_sessions.py` | **Satisfied** (Redis window) |
| **G3** | Multiple data formats | Good | `app/services/parsers/` (pdf, docx, md, txt, web) | `tests/test_ssrf.py`, `tests/test_lifecycle_consistency.py` | **Satisfied** |
| **G4** | KB updates without retraining | Good | `app/api/v1/documents.py`, `app/workers/tasks_*.py` | `tests/test_lifecycle_consistency.py` | **Satisfied** |
| **G5** | Authentication for users & admins | Good | `app/core/security.py`, `app/api/v1/auth.py` | `tests/test_auth.py` | **Satisfied** |
| **G6** | API documentation | Good | `app/main.py` (`/docs`, `/redoc`) | `tests/test_health.py` | **Satisfied** |
| **G7** | Backend logger | Good | `app/core/logger.py`, `app/models/sql_models.py` | `tests/test_health.py`, `tests/test_rag_pipeline.py` | **Satisfied** |
| **S1** | Complete frontend | System | `frontend/src/app/`, `frontend/src/components/` | Automated integration scripts | **Satisfied** |
| **S2** | Backend for queries & KB | System | `app/main.py`, `app/workers/celery_app.py` | 75/75 pytest tests | **Satisfied** |
| **S3** | Clean API-based architecture | System | `app/api/router.py`, `app/api/v1/` | Full test suite | **Satisfied** |
| **E1** | Persistent per-user chat history | Extension | Missing DB tables, endpoints, and frontend sidebar | Missing `test_chat_history.py` | **Gap Identified** (Scheduled for 7c) |
| **E2** | Registration, logout, password change | Extension | Missing logout revocation, `/register` UI, password change | Missing `test_no_demo_credentials.py` | **Gap Identified** (Scheduled for 7b) |
| **E3** | Admin user management | Extension | Missing `GET/PATCH /users`, missing `AdminUsers` tab | Missing `test_users_admin.py` | **Gap Identified** (Scheduled for 7d) |

### Checklist 6: Security Hardening (Architecture §9)
- **Upload Security (§9.2):** File uploads in `backend/app/api/v1/documents.py:47-73` enforce magic-byte verification (`%PDF-`, `PK\x03\x04`), extension allowlist (`pdf`, `docx`, `md`, `txt`), and max size cap (`MAX_UPLOAD_MB`). Files are stored under UUID filenames.
- **SSRF Defenses (§9.3):** Implemented in `backend/app/services/parsers/web.py:30-100`. Tested in `tests/test_ssrf.py` (8 passing tests). Blocks private IPv4/IPv6 subnets, loopback, link-local metadata endpoints (`169.254.169.254`), non-HTTP schemes, and enforces domain allowlists.
- **Prompt Injection (§9.4):** Context is strictly delimited as untrusted data in `build_answer_prompt()`. The 3-layer guardrail prevents injection exploits from exfiltrating or fabricating answers.
- **Rate Limiting (§9.5):** Redis sliding counter implemented in `backend/app/core/rate_limit.py`. Applied to `/auth/login` (5/min) and validated in `tests/test_auth.py`.
- **CORS (§9.5):** Configured in `backend/app/main.py:67-73` using `settings.CORS_ORIGINS`, restricted by default to `["http://localhost:3000"]`.
- **Security Headers:** Missing from both FastAPI and Next.js.
- **Secrets in Logs (§9.6):** `settings.LLM_API_KEY` uses Pydantic `SecretStr`. Masking utilities in `app/services/llm/` prevent API keys from appearing in log streams.

### Checklist 7: Test Stability & Flakiness
- **Execution Run 1:** 75 passed in 33.35s (0 failures, 0 skipped, 0 warnings).
- **Execution Run 2:** 75 passed in 31.55s (0 failures, 0 skipped, 0 warnings).
- **Flakiness Assessment:** 0% flakiness detected.
- **Untested Features:**
  - Token revocation via Redis upon logout.
  - PostgreSQL-backed persistent chat history across logins.
  - Administrative user role modification and deactivation.
  - Server-side password length enforcement.

### Checklist 8: Dependency Security Audit
- **Backend (`pip-audit`):**
  - Tool was installed and run directly within the containerized Python environment.
  - Result: 2 known vulnerabilities identified in container base package `setuptools 79.0.1` (`PYSEC-2026-3447`). Fixed in `setuptools 83.0.0`.
  - All core application dependencies (`fastapi`, `sqlalchemy`, `qdrant-client`, `argon2-cffi`, `redis`, `httpx`, `pymupdf`, `python-docx`, `pydantic`, `celery`) have **zero reported vulnerabilities**.
- **Frontend (`npm audit`):**
  - Audited 107 packages in an isolated environment mirroring `frontend/package.json`.
  - Result: 9 vulnerabilities (1 Critical, 6 High, 2 Moderate).
  - Primary driver: `next@14.2.0` (Critical advisory regarding DoS, request smuggling, and Server Actions SSRF). Upgrading Next.js to the latest 14.x patch release resolves these issues.
  - Notice: `frontend/package-lock.json` is currently not checked into git.

### Checklist 9: UX Gaps & Interface Polish
- **Missing Pages:** `/register` (registration form) and `/account` (password change) do not exist.
- **Empty States:** `ChatWindow.tsx` has a clean initial empty state displaying system capabilities. `AdminDocManager.tsx` handles empty document lists properly.
- **Streaming Controls:** The send button is disabled during generation; an Abort/Stop button is not yet provided.
- **Markdown Formatting:** Text is rendered using `whitespace-pre-wrap` with citation chips, without full markdown parser support for headings, bold, code snippets, or markdown tables.
- **Mobile Responsiveness:** Desktop layout is well-proportioned; mobile sidebar drawer toggle exists, but requires minor polish on small viewports.
- **Accessibility:** Form controls feature semantic IDs and labels. Icon-only action buttons require `aria-label` additions.

### Checklist 10: Operations & Maintainability
- **Clean Start:** Documented in `README.md`. Docker Compose launches all 7 containers successfully.
- **Health Checks:** `/api/v1/health` checks PostgreSQL, Redis, and Qdrant connectivity. Docker Compose includes healthchecks on all services, though Celery containers use a dummy process exit check.
- **Logging & Tracing:** Loguru JSON logging with automatic 10MB rotation, 14-day retention, and `X-Request-ID` middleware propagation functions as designed.
- **Data Retention & Backups:** `query_logs` table has no pruning policy; snapshot/backup procedures are not yet detailed in documentation.

---

## Prioritized Remediation Roadmap

Based on the audit findings, remediation is structured into the following sequential implementation phases:

### Phase 7b: Security Fixes, Registration & Account Features
1. **Remove Demo Credentials:** Eliminate `handleFillDemoAdmin` and the "Fill Demo Admin Credentials" button from `frontend/src/components/LoginForm.tsx`. Remove default credentials from `README.md`.
2. **Configuration Sanitization:** Replace concrete defaults in `.env.example` with placeholders; remove default fallback for `JWT_SECRET_KEY` in production; add `PASSWORD_MIN_LENGTH = 10`.
3. **Token Revocation & Logout:** Implement `jti` in `create_refresh_token()`; build `POST /auth/logout` setting Redis marker `revoked:{token_id}`; verify revocation during `POST /auth/refresh`; update frontend `logout()` to call this endpoint.
4. **Registration UI:** Build `RegisterForm.tsx` at `/register` with client validation and link to/from `/login`.
5. **Password Change & Account Page:** Implement `POST /auth/change-password` (verifying current password) and build a user account management view.
6. **Security Headers:** Add CSP, `X-Content-Type-Options`, `X-Frame-Options`, and `Referrer-Policy` to FastAPI and Next.js.
7. **Automated Security Tests:** Create `tests/test_no_demo_credentials.py` to assert that no default secrets or demo strings exist in the codebase.

### Phase 7c: Persistent Chat History
1. **Database Schema:** Create Alembic migration `002_chat_history.py` adding `chat_sessions` and `chat_messages` tables.
2. **History Persistence:** Update `POST /chat/stream` to save user messages and completed assistant answers to PostgreSQL. Store fallback text on retract; never store partial errors as answers.
3. **Session API:** Implement `GET /chat/sessions` (newest first), `GET /chat/sessions/{id}/messages`, `PATCH /chat/sessions/{id}` (rename), and `DELETE /chat/sessions/{id}` with strict owner isolation.
4. **Cache Reconstruction:** Update `SessionManager` to reconstruct Redis history from PostgreSQL when the Redis key is expired or flushed.
5. **Frontend History Sidebar:** Build `ChatHistorySidebar.tsx` to list past conversations, restore messages and citations upon click, rename sessions, and persist across login/logout.
6. **Automated History Tests:** Author `tests/test_chat_history.py`.

### Phase 7d: Admin User Management
1. **User Management API:** Implement `GET /api/v1/users` and `PATCH /api/v1/users/{id}` (role change, activation/deactivation).
2. **Safety Invariants:** Prevent admin self-demotion or self-deactivation; protect the last active administrator from demotion; block deactivated users from logging in or refreshing tokens.
3. **Frontend Admin Users Tab:** Add `AdminUsers.tsx` tab to the admin dashboard for managing accounts.
4. **Automated User Admin Tests:** Author `tests/test_users_admin.py`.

### Phase 7e: Final Evaluation, README & Clean-Start Verification
1. **Benchmarking:** Execute calibration sweep on `calibration_set.json` and full evaluation on `test_set.json`; record real metrics in `docs/eval-report.md`.
2. **Dependency Updates:** Upgrade Next.js to secure patch release; generate and commit `package-lock.json`; upgrade container `setuptools`.
3. **Clean-Start Verification:** Test fresh clone deployment from `.env.example`.
4. **Production Documentation:** Finalize `README.md` with updated architecture diagrams, security guidelines, privacy disclosures, and demo walkthrough.
