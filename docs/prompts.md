# Build Prompts (aligned with architecture V4 + provider-agnostic LLM layer)

Save this as `docs/prompts.md`. Run the prompts in order, one per Planning-mode task. Read each plan before approving it, run the acceptance checks yourself, and commit after every phase.

**Order:** Setup → 0 → 1 → 1.5 → 2 → 3 → 4 → 5 → 6 → 7a → 7b → 7c → 7d → 7e

---

## How to start and end every session

**Start** (paste before each prompt):

```text
Read docs/architecture.md and docs/progress.md. Tell me in 3 lines where we are, then do this task:
```

**End:** run `/update-progress` (the workflow), then review the diff of `docs/progress.md` and commit.

---

## Setup files

### `.agent/rules/project.md` (replace the earlier version)

```text
# Project rules
- At the start of every task, read docs/architecture.md and docs/progress.md. architecture.md is the source of truth. If a task conflicts with it, stop and ask me.
- At the end of every task, update docs/progress.md: tick finished items, add a session log entry (what was done, tests run and their real results, files changed, what is unfinished), record deviations from the architecture, and set "Next task". Never mark a phase or requirement done unless its acceptance tests ran and passed. If progress.md and the code disagree, tell me before continuing.
- Stack: Python 3.11, FastAPI, SQLAlchemy 2 + Alembic, Celery + Redis, Qdrant, Loguru. Frontend: Next.js (App Router), TypeScript, Tailwind.
- All secrets and settings come from environment variables. Never hardcode keys or model names. Keep .env.example current. Never commit .env.
- Models, thresholds, chunk sizes and limits live in app/core/config.py only.
- All LLM calls go through app/services/llm/ (base, openai_compat, anthropic, factory). The provider is chosen by LLM_PROVIDER, LLM_BASE_URL and LLM_API_KEY. No provider-specific features (native JSON mode, tool calling, prefill) outside the adapters.
- Embeddings go through the embedding interface and the EMBEDDING_* settings. Never hardcode an embedding model or dimension.
- Never log or return passwords, tokens or API keys.
- Every task: write or update pytest tests, RUN them, and report real results. Never say something works without running it.
- Small, reviewable changes. End each task with a list of files changed and anything unfinished. No unrelated refactors.
- Type hints everywhere, Pydantic schemas for all API input and output, docstrings on public functions.
- Ask before adding a dependency that is not in the architecture doc.
```

### Workflow `/update-progress`
(Already created. Keep the description and content from before.)

### `docs/progress.md` phase checklist (add 1.5)

```text
- [ ] 0 Scaffold, config, logging, /health
- [ ] 1 DB models, migrations, auth, rate limiting
- [ ] 1.5 LLM provider layer (OpenAI-compatible and Anthropic adapters)
- [ ] 2 Embeddings, parsers, ingestion, document lifecycle
- [ ] 3 Hybrid retrieval, rerank, Layer 1 fallback
- [ ] 4 Router, memory, generation, citations, SSE chat
- [ ] 5 Frontend (login, chat, admin)
- [ ] 6 Evaluation and threshold calibration
- [ ] 7a Full audit (no code changes), docs/audit.md
- [ ] 7b Security fixes, registration, logout, change password
- [ ] 7c Persistent chat history
- [ ] 7d Admin user management
- [ ] 7e Final eval, README, clean start
```

---

## Prompt 0: Scaffold, config, logging, health

```text
Task: Phase 0, scaffold, configuration, logging and health.

Read docs/architecture.md (sections 2, 3, 10, 12, 15, 17). Create the monorepo skeleton exactly as in section 15, with empty placeholder files where later phases will fill them in: frontend/, backend/, sample_kb/, docs/, docker-compose.yml, Makefile, .env.example, .gitignore, README.md stub. Do not touch .agent/ and only update docs/progress.md as the rules require.

Backend:
- FastAPI app: app/main.py, api/router.py, api/v1/health.py.
- app/core/config.py using pydantic-settings with EVERY setting from architecture section 12 (including LLM_*, FAST_LLM_*, ANSWER_LLM_*, EMBEDDING_*, ADMIN_EMAIL, ADMIN_PASSWORD), read from the environment, with the defaults in that table. Secrets are never printed. Settings that are required for the LLM (LLM_API_KEY, FAST_MODEL, ANSWER_MODEL) are only enforced when the LLM layer is first used, so the app still starts without them.
- app/core/logger.py: Loguru JSON logging to stdout AND to a rotating file logs/app.log (rotate at 10 MB, keep 14 days, create the logs/ folder automatically), plus a request-ID middleware that puts a request ID on every log line and in an X-Request-ID response header.

docker-compose.yml: services api, worker, beat (Celery scheduler, placeholder for now), frontend (placeholder), postgres, redis, qdrant. Named volumes for postgres, qdrant, uploaded files and a model cache (Hugging Face cache) so models download once. Mount ./logs into api and worker. Health checks on every service.

.env.example lists every setting with comments and includes ready-to-uncomment LLM blocks for: OpenAI, OpenRouter, Gemini (OpenAI-compatible endpoint) and Anthropic (LLM_PROVIDER, LLM_BASE_URL, LLM_API_KEY, FAST_MODEL, ANSWER_MODEL). Add logs/ and .env to .gitignore.

Makefile targets: up, down, logs, test (runs pytest inside the api container against the compose services), eval, lint.

GET /api/v1/health reports the status of Postgres, Redis and Qdrant and whether an LLM is configured. It must never make a paid LLM call. /docs and /redoc must load.

Acceptance: docker compose up starts everything healthy; curl /api/v1/health shows all services; logs/app.log exists and contains a JSON line with a request ID; the app exits with a clear message if a setting has an invalid value. Run these checks and show me the output.
```

---

## Prompt 1: Database and authentication

```text
Task: Phase 1, database and authentication. Read architecture sections 4.1, 8 and 9.

- SQLAlchemy 2 models and Alembic migrations for users, documents (all fields and status values from 4.1, unique sha256 among non-deleted documents) and query_logs.
- Auth endpoints: POST /auth/register (role is ALWAYS "user"), POST /auth/login, POST /auth/refresh, GET /auth/me. Argon2 or bcrypt hashing, short-lived access tokens plus refresh tokens, and require_user and require_admin dependencies.
- scripts/seed_admin.py, and optional seeding at startup when ADMIN_EMAIL and ADMIN_PASSWORD are set. Admins are never created through the API.
- Redis-backed rate limiting (stricter on /auth/login), CORS from CORS_ORIGINS, and the standard error format {detail, code} with correct status codes (401, 403, 404, 409, 413, 422, 429, 503).

Acceptance: pytest tests prove that registering cannot create an admin; a normal user gets 403 on an admin route while an admin gets through; expired and invalid tokens are rejected; refresh works; login rate limiting triggers; migrations apply cleanly on an empty database. Run them and show me the results.
```

---

## Prompt 1.5: LLM provider layer

```text
Task: Phase 1.5, LLM provider layer. Read architecture sections 6.9 and 12.

Create app/services/llm/ with:
- base.py: the interface complete(system, messages, model, max_tokens, temperature) -> str and stream(...) -> AsyncIterator[str], plus normalized errors LLMAuthError, LLMRateLimitError, LLMTimeoutError, LLMUnavailableError.
- openai_compat.py: OpenAI SDK with a custom base_url (covers OpenAI, OpenRouter, Gemini's OpenAI-compatible endpoint, Ollama, vLLM).
- anthropic.py: native Anthropic SDK; the system prompt goes in the system parameter.
- factory.py: builds an adapter per role (router and answer) from the FAST_LLM_* and ANSWER_LLM_* overrides, falling back to the shared LLM_* settings.

Requirements: retries with exponential backoff on 429 and 5xx (LLM_MAX_RETRIES), timeouts from LLM_TIMEOUT_SECONDS, base URL validation (https required except localhost and private hosts, trailing slash normalized), and API key masking so a key can never appear in logs or error messages. Do not rely on native JSON mode, tool calling or prefill.

Also add scripts/llm_check.py: it sends one tiny test prompt through both roles and prints provider, model and latency, never the key. Update .env.example if anything is missing.

Acceptance: tests/test_llm_adapters.py with mocked HTTP prove system prompt placement for both adapters, streaming, error mapping, retries, base URL validation, and that the key never appears in logs. Run them. Then I will put my real key in .env and you run scripts/llm_check.py and show me the output.
```

---

## Prompt 2: Embeddings, ingestion and document lifecycle

```text
Task: Phase 2, embeddings, ingestion and document lifecycle. Read architecture sections 4, 5, 9.2, 9.3 and 12.

Embeddings:
- An embedding interface with two backends chosen by EMBEDDING_PROVIDER: local (default BAAI/bge-m3) and openai_compatible (an /embeddings endpoint using EMBEDDING_BASE_URL, EMBEDDING_API_KEY, EMBEDDING_MODEL).
- Sparse vectors: BM25 via fastembed.
- Qdrant collection kb_chunks with named vectors dense and sparse, payload indexes on document_id and is_active, and the embedding guard from section 4.2 (store the embedding model name and dimension in the collection metadata, and refuse to start or to write when they do not match the config).
- scripts/reindex.py that re-embeds every active document from its stored source file.

Parsers (app/services/parsers/): PDF (PyMuPDF, page numbers kept), DOCX (python-docx), Markdown, TXT, and web URL (httpx + BeautifulSoup) with full SSRF protection: domain allowlist from ALLOWED_URL_DOMAINS (an empty list DISABLES URL ingestion with a clear error), block private, loopback and link-local addresses after DNS resolution, re-validate on every redirect, redirect limit, timeouts, response size cap. Optional OCR behind ENABLE_OCR (pytesseract), best effort.

Chunking: 500-800 tokens (config), 10-15% overlap, split on headings and paragraphs first, keep page, section and source_name metadata. chunk_id must be deterministic (hash of document_id, version, chunk_index) so upserts are idempotent.

Upload API (admin only): POST /documents (file or URL, returns 202), PUT /documents/{id} (new version), GET /documents, GET /documents/{id}/status, DELETE /documents/{id}. Validate extension allowlist, magic bytes, size limit, and reject duplicate sha256 with 409 and the existing document ID. Store files under random filenames in the uploads volume.

Celery tasks (workers/): blue-green ingest and update exactly as in section 5.5 (pending_version, chunks inserted with is_active=false, cutover, purge old version, failure cleanup with last_error), two-phase delete as in 5.6 (set status deleting and flip is_active=false first), heartbeat_at updates during long tasks, and a periodic reconcile task as in 5.7. Run the scheduler as the beat service in docker-compose.yml. Use acks_late, bounded retries with backoff, and make every task idempotent.

Acceptance: tests/test_lifecycle_consistency.py (real Qdrant via the compose service or a test container) proves: the old version stays searchable until cutover; a failed update leaves the old version live and removes partial chunks; delete hides the document immediately and purges later; uploading the same file twice is rejected; the reconciler recovers a row with a stale heartbeat; running a task twice causes no duplicates. tests/test_ssrf.py covers private IPs, redirects to private IPs, oversized responses and non-allowlisted domains. Run them and show me the results. Then ingest two files from sample_kb through the API and show me the document status moving to active.
```

---

## Prompt 3: Hybrid retrieval, reranking and Layer 1

```text
Task: Phase 3, retrieval. Read architecture sections 6.3 and 6.4.

Implement app/services/rag_engine.py retrieval:
- Hybrid search through the Qdrant Query API: prefetch on dense and sparse vectors, fuse with Reciprocal Rank Fusion, ALWAYS filter on is_active == true, return RETRIEVAL_TOP_K candidates (default 15). Use the embedding interface and EMBEDDING_* settings, never a hardcoded model.
- Rerank with the cross-encoder in RERANKER_MODEL, load it once at startup (singleton), keep RERANK_TOP_N (default 4).
- Layer 1: if the best rerank score is below RERANK_THRESHOLD, return a result object marked as fallback. The threshold comes only from config.
- Return a structured result with chunks, scores, the decision and per-stage latency. Log scores and latency for each stage with the request ID.
- Report the embedding and reranker model status in /health.

Add scripts/search.py: `python -m scripts.search "question"` prints the standalone result with scores and the decision.

Note: the first run downloads the embedding and reranker models into the cache volume.

Acceptance: run scripts/search.py on sample_kb for these questions and show me the top scores for each: [paste 5 in-scope and 5 out-of-scope questions of yours]. Also prove with a test that a deactivated document (is_active=false) never appears in results. Based on the scores, suggest an initial RERANK_THRESHOLD, but do not hardcode it.
```

---

## Prompt 4: Router, memory, generation, citations and streaming

```text
Task: Phase 4, the chat pipeline. Read architecture sections 6, 7 and 8.

Implement:
- session_manager.py: Redis, key session:{user_id}:{session_id}, last HISTORY_MESSAGES messages, SESSION_TTL_HOURS sliding TTL. Fallback and clarification messages are stored with a kind marker so the router does not treat them as knowledge. If Redis is down, chat continues without memory and the failure is logged.
- intent_router.py: one call through the FAST role of the LLM layer. The prompt asks for JSON {intent, clarification_message, standalone_query}; validate it with Pydantic, retry once on invalid output, then fail open to SEARCH with the raw user message. GREETING returns the canned GREETING_MESSAGE from config (never free generation); messages that mix a greeting with a question are SEARCH. The rewrite must not add facts that are not in the conversation.
- Generation through the ANSWER role of the LLM layer. The answer prompt receives the standalone query and the retrieved chunks, NOT the raw history. Chunks are tagged [C1]..[C4] and marked as untrusted data; document names and pages are never shown to the model. System prompt rules exactly as in section 6.5, including the [[NOT_FOUND]] sentinel.
- Layer 2: buffer the first ~15 characters of the stream; if they match the start of [[NOT_FOUND]], abort and send the FALLBACK_MESSAGE.
- Layer 3 and citations (citation_service.py): after generation, extract [Cn] tags, drop tags that were not in the context, and if no valid tag remains send a retract event with the fallback. Otherwise resolve tags to {document, page, section, chunk_id} and send a citations event.
- POST /chat/stream as SSE (token, citations, retract, error, done, payloads exactly as in section 6.8), GET /chat/sessions, DELETE /chat/sessions/{id} (owner only).
- Write one query_logs row per query: intent, original and standalone query, top score, threshold, fallback layer, cited chunk IDs and per-stage latency.
- LLM errors become an error event with the system error message and are logged without secrets.

Acceptance: tests/test_rag_pipeline.py with a mocked LLM prove each path: greeting, clarify, follow-up rewrite using history, Layer 1 fallback, Layer 2 sentinel (including a sentinel split across stream chunks), Layer 3 retract, a hallucinated citation tag removed, router JSON failure failing open, Redis down still answering. tests/test_sessions.py proves another user cannot read or delete my session, the history cap and the TTL. Run them, then do one real end-to-end chat with curl against the running API using sample_kb documents and show me the event stream.
```

---

## Prompt 5: Frontend

```text
Task: Phase 5, frontend. Read architecture sections 1, 6.8 and 11.

Build the Next.js (App Router, TypeScript, Tailwind) frontend with its own Dockerfile and a NEXT_PUBLIC_API_URL setting:
- Login page and token handling (access plus refresh, automatic refresh), role-aware routing using GET /auth/me.
- Chat page: streamed tokens using fetch streaming with the bearer token (NOT the browser EventSource), message bubbles, citation chips that open a CitationsDrawer (document, page, section), correct handling of the retract event (replace the shown answer with the fallback text), error events, a new-chat button that calls DELETE on the session, a session list from GET /chat/sessions, disabled input while streaming, loading and error states.
- Admin page (AdminDocManager): file upload and URL ingest, a documents table with status (Pending, Processing, Active, Updating, Deleting, Failed) that polls while any document is in progress, last_error shown for failed documents, new version upload and delete with confirmation. Visible to admins only.
- Responsive layout.
- services/streamChat.ts parses the events defined in section 6.8.

Acceptance: run the full stack with docker compose. If you can use the browser, log in as the seeded admin, upload a document from sample_kb, wait for Active, then ask an in-scope question, an out-of-scope question and a greeting, and give me screenshots. Otherwise give me the exact manual steps and expected results to verify. Also confirm that a normal user cannot open the admin page.
```

---

## Prompt 6: Evaluation and calibration

```text
Task: Phase 6, evaluation and calibration. Read architecture section 13.

Create backend/eval/ with:
- calibrate_threshold.py: reads calibration_set.json, runs retrieval and reranking for each question, sweeps thresholds, reports precision and recall for in-scope versus out-of-scope, and writes the recommended RERANK_THRESHOLD to a results file. It must NEVER read test_set.json.
- run_eval.py: runs test_set.json against the running API (login, then /chat/stream with the history given per question) and reports answer accuracy, router accuracy, fallback accuracy per layer, citation validity (checked in code), per-category results and a list of failures. Write eval/results/<timestamp>.json and a readable summary markdown. Answer correctness is judged by checking expected_facts against the answer text, and an optional LLM-as-judge step through the LLM layer, clearly labeled.
- A make eval target.

Question schema: {id, category, history, question, expected_behavior, expected_facts, source_doc}. I will provide calibration_set.json and test_set.json. Create small example files with 3 questions each so the scripts can be tested.

Acceptance: both scripts run on the example files and show output. Do not invent real results.
```

**Optional, to draft questions (you must verify every answer yourself):**

```text
Read the documents in sample_kb/. Draft question candidates in the schema above: for the calibration set 30 questions (mix of in-scope, topical out-of-scope and unrelated), and for the test set 50 questions with the category counts in architecture section 13.1. For each in-scope question include expected_facts quoted from the source and the source_doc. Do not run the system. Mark all of it as DRAFT for my manual verification.
```

Then verify every expected answer against the source documents before using the files.

---

## Prompt 7a: Full audit (no code changes)

```text
Task: Phase 7a, full audit. Do NOT change any code in this task. Create docs/audit.md.

Audit the whole project against docs/architecture.md (including the updated sections 4.1, 7, 8, 9 and 11), the original requirements (core 1-3, good-to-have 1-7, system 1-3, extensions E1-E3) and the checklist below. For each finding give: severity (Critical / High / Medium / Low), file and line, what is wrong, and the proposed fix.

Checklist:
1. Secrets and demo credentials: search the frontend, backend, README, .env.example, docker-compose.yml, scripts and tests for hardcoded or prefilled credentials, "demo", "admin@", default passwords and default JWT secrets. Check the built frontend bundle too. Search the git history (git log -S) for any real secret. A "fill demo admin credentials" control or any default admin login is Critical.
2. Authentication flows: registration UI, role always "user", login, logout (does it revoke the refresh token?), refresh, change password, password policy, token storage, generic error messages.
3. Authorization: every admin route and admin page requires admin; conversation ownership; no way to escalate.
4. Chat history: is it persisted per user across logout and login? Where, and for how long? Can one user read another's history?
5. Every requirement in architecture section 1.1: file, test and evidence.
6. Security items in section 9: uploads, SSRF, injection, rate limits, CORS, security headers, secrets in logs.
7. Tests: run the whole suite twice; list untested features, skipped and flaky tests.
8. Dependencies: run pip-audit and npm audit and summarize.
9. UX gaps: missing pages, empty and error states, stop-generation, markdown rendering, accessibility basics, mobile layout.
10. Operations: clean start from a fresh clone, health checks, log rotation, backups note, README completeness.

Finish with a prioritized fix list. Show me docs/audit.md.
```

---

## Prompt 7b: Security fixes, registration and account features

```text
Task: Phase 7b. Read docs/audit.md and architecture sections 8, 9.1 and 11. Fix every Critical and High security finding first, then implement:
1. Remove ALL demo or prefilled credentials and any "fill demo admin credentials" control from the frontend, README and examples. The login page contains only a normal form. Admin credentials come only from ADMIN_EMAIL and ADMIN_PASSWORD in .env (placeholders in .env.example). Tell me exactly which secrets I must rotate by hand if any were ever committed.
2. A registration page (RegisterForm) at /register, linked from login and back: email, password and confirm password, client-side validation, clear server errors, PASSWORD_MIN_LENGTH enforced server-side, role always user, then redirect to login or sign in automatically.
3. POST /auth/logout that revokes the refresh token (revocation marker in Redis keyed by token id, TTL equal to the remaining lifetime). The frontend calls it on logout and clears all client state.
4. POST /auth/change-password (current password required) and a small account page in the frontend.
5. Security headers on the frontend (Content-Security-Policy, X-Content-Type-Options, Referrer-Policy, frame protection) and on the API where relevant.

Tests: registration cannot create an admin, weak passwords are rejected, logout makes the refresh token unusable, changing the password invalidates the old one, and tests/test_no_demo_credentials.py fails if demo credentials or default secrets appear in the repo. Run all tests.
Acceptance: show me the test output, the login page without any demo control, and the grep output proving no credentials in the repo or the built bundle.
```

---

## Prompt 7c: Persistent chat history

```text
Task: Phase 7c, persistent chat history. Read architecture sections 4.1 (chat_sessions, chat_messages), 7, 8 and 11 (they were updated). Implement:
- Alembic migration and models for chat_sessions and chat_messages.
- POST /chat/stream saves the user message before generation and the assistant message (text, citations, kind, fallback_layer) after the stream ends; a retract stores the fallback text; failures never store partial text as an answer. An unknown session_id creates a session for the current user; a session owned by someone else returns 404. Title = first user message truncated to 60 characters.
- GET /chat/sessions (newest first), GET /chat/sessions/{id}/messages, PATCH /chat/sessions/{id} (rename), DELETE /chat/sessions/{id} (PostgreSQL and the Redis key). All owner-only.
- The Redis window stays the router's source; rebuild it from PostgreSQL when it is missing or Redis is down.
- Frontend: ChatHistorySidebar listing conversations; opening one restores the messages and citation chips; rename; delete with confirmation; new chat; history persists after logout and login.

Tests (tests/test_chat_history.py): history survives a new login, owner-only access (404 for others), messages restored with citations, retract stored correctly, delete removes everything, Redis flushed then history rebuilt. Run them.
Acceptance: log in, chat, log out, log in again, and the conversation is there with working citations; a second user cannot see it. Give me screenshots if you can use the browser.
```

---

## Prompt 7d: Admin user management (recommended)

```text
Task: Phase 7d, user management. Read architecture sections 8, 9.1 and 11. Implement GET /users and PATCH /users/{id} (change role, activate or deactivate), admin only. Rules: an admin cannot demote or deactivate themselves; the last active admin cannot be demoted or deactivated; deactivated users cannot log in or refresh; every change is logged without secrets. Frontend: an AdminUsers tab on the admin page with a users table and role change and activate/deactivate with confirmation.
Tests (tests/test_users_admin.py): the rules above plus 403 for normal users. Run them.
```

---

## Prompt 7e: Final evaluation, README and clean start

```text
Task: Phase 7e, wrap-up.
1. Run the full test suite and the evaluation (calibrate on the calibration set, then run the test set). Record the real results in docs/eval-report.md, including failures.
2. Verify a clean start from a fresh clone with only .env created from .env.example: docker compose up works, the admin is seeded from .env, a new user can register, documents upload through the UI, and chat works with history kept after logout.
3. Write README.md: overview, architecture diagram, setup, environment variables (with LLM provider presets), seeding the admin, registration, supported formats and limits, a privacy note (what is stored: chat history and query logs), running tests and evaluation, API overview with a /docs link, evaluation results, known limitations, and a short demo script (upload, ask, update the document, ask again, delete, ask again).
4. Fill docs/decisions.md.
5. Update docs/audit.md so every finding is marked fixed or accepted with a reason.
Acceptance: show me the final test and eval output and the README.
```

---

## Reusable helper prompts

**Bug fix**

```text
Problem: [what you expected vs what happened]. Command I ran: [command]. Exact error: [paste]. Relevant files: [paths]. First find the root cause and explain it in plain language, then propose the smallest fix, then apply it and run the relevant tests.
```

**Understand the code (for your viva)**

```text
Explain [file or feature] in plain language: what problem it solves, how data flows through it, and why the design in architecture.md section [n] requires it. Then give me 5 questions an examiner might ask about it, with short answers.
```

**Review before committing**

```text
Review the changes in this task against docs/architecture.md. List deviations, missing tests, unhandled errors and anything that could leak a secret. Do not change code yet.
```