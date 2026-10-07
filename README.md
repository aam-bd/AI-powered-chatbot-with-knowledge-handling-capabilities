# Enterprise Knowledge-Base AI Chatbot (RAG)

An enterprise-grade, retrieval-augmented generation (RAG) chatbot designed to answer questions **strictly and exclusively** from a custom knowledge base (KB) of documents. The system enforces strict hallucination guardrails, grounds all answers with verified source citations, and provides a full-featured streaming web interface and admin portal.

---

## 1. System Architecture

```
                                  ┌──────────────────────────────────────────────┐
                                  │           Next.js 14 Frontend UI             │
                                  │  • Login (JWT Refresh)  • Admin Portal (KB)  │
                                  │  • Real-Time Chat (Fetch SSE Stream)         │
                                  │  • Citations Drawer     • Retract Handling   │
                                  └──────────────────────┬───────────────────────┘
                                                         │ HTTPS (Bearer JWT / SSE)
                                                         ▼
                                  ┌──────────────────────────────────────────────┐
                                  │               FastAPI API Server             │
                                  │  • Request-ID Tracing   • Strict CORS        │
                                  │  • Redis Rate Limiting  • OpenAPI /docs      │
                                  │  • Role-Based Auth      • Telemetry Logging  │
                                  └──────┬───────────────┬──────────────┬────────┘
                                         │               │              │
                       ┌─────────────────▼──┐   ┌────────▼────────┐   ┌─▼──────────────────────┐
                       │    PostgreSQL 15   │   │  Redis 7 Cache  │   │     Qdrant Vector DB   │
                       │ • Users & Roles    │   │ • Session Store │   │ • Dense Vectors        │
                       │ • Document State   │   │ • Rate Counters │   │ • Sparse BM25 Vectors  │
                       │ • Query Audit Logs │   │ • Celery Broker │   │ • RRF Universal Query  │
                       └─────────────────▲──┘   └────────┬────────┘   └─▲──────────────────────┘
                                         │               │              │
                                         └───────┬───────┴──────┬───────┘
                                                 │              │
                                  ┌──────────────▼──────────────▼────────────────┐
                                  │            Celery Background Workers         │
                                  │  • Document Parsers (PDF, DOCX, MD, TXT, Web)│
                                  │  • Blue-Green Updates & Reconciler Beat      │
                                  │  • Two-Phase Soft/Hard Deletion              │
                                  └──────────────────────────────────────────────┘
                                                         │
                                                         ▼
                                  ┌──────────────────────────────────────────────┐
                                  │     LLM Provider Layer (openai / anthropic)  │
                                  │  • FAST Router: Query classification/rewrite │
                                  │  • ANSWER Role: Grounded generation          │
                                  └──────────────────────────────────────────────┘
```

### Three-Layer Grounding Guardrails

To fulfill the strict non-negotiable requirement that the model answers **only** from the knowledge base:
1. **Layer 1 (Retrieval Score Gate)**: Hybrid retrieval (dense `bge-m3` + sparse BM25 fused via Reciprocal Rank Fusion) is scored by a cross-encoder reranker (`bge-reranker-base`). If the top candidate score falls below `RERANK_THRESHOLD` (calibrated at $0.50$), the query is immediately rejected with `FALLBACK_MESSAGE` without calling the LLM.
2. **Layer 2 (Sentinel Buffer Window)**: The generation prompt instructs the LLM to output `[[NOT_FOUND]]` if the retrieved text lacks the answer. The streaming pipeline buffers the first 15 characters. If the sentinel appears across any token boundaries, generation is cleanly aborted and replaced with the fallback message before any tokens leak to the user.
3. **Layer 3 (Citation Grounding Retraction)**: Post-generation parser extracts `[Cn]` source tags and validates them against the injected context chunks. Hallucinated tags are pruned. If no valid grounded citations remain, an SSE `retract` event is dispatched, instructing the frontend to replace the ungrounded text with the canned fallback message.

---

## 2. Technology Stack

- **Frontend**: Next.js 14 (App Router), TypeScript, Tailwind CSS, fetch-based SSE streaming, standalone multi-stage Alpine Docker container.
- **Backend API**: FastAPI (Python 3.11), Loguru JSON logging with `X-Request-ID` tracing, Pydantic v2 settings & schemas.
- **Workers**: Celery with Redis broker and Celery Beat scheduler for background ingestion, blue-green updates, reconciliation, and two-phase deletion.
- **Relational Database**: PostgreSQL 15, SQLAlchemy 2 (asyncpg), Alembic migrations.
- **Vector Database**: Qdrant (`v1.11.0`), named vectors `dense` (1024-dim cosine) and `sparse` (BM25), with Embedding Guard verification.
- **Embeddings & Reranker**: FastEmbed ONNX local CPU models (`BAAI/bge-large-en-v1.5` dense, `Qdrant/bm25` sparse, `BAAI/bge-reranker-base` cross-encoder).
- **LLM Layer**: Unified provider abstraction supporting any OpenAI-compatible API (Google Gemini, OpenAI, OpenRouter, Ollama, vLLM) and native Anthropic Messages API.

---

## 3. Quick Start Guide (Clean Start Verification)

### Prerequisites
- Docker Engine 24+ and Docker Compose v2+
- Git

### Step 1: Clone Repository & Create Environment Configuration
```bash
git clone https://github.com/aam-bd/AI-powered-chatbot-with-knowledge-handling-capabilities.git
cd AI-powered-chatbot-with-knowledge-handling-capabilities

# Copy template configuration
cp .env.example .env
```

### Step 2: Configure LLM Provider in `.env`
Choose one of the presets in `.env`. By default, Google AI Studio (Free Tier) is configured:

```bash
# --- Preset 3: Google Gemini (Google AI Studio OpenAI-compatible endpoint) ---
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_API_KEY=your_actual_google_ai_studio_api_key_here
FAST_MODEL=gemini-3.1-flash-lite
ANSWER_MODEL=gemini-3.1-flash-lite
```

*(Alternative presets for OpenAI, OpenRouter, and native Anthropic are documented directly in `.env.example`.)*

### Step 3: Launch System Containers
```bash
make up
# or: docker compose up -d --build
```
This launches 7 orchestrated services:
- `chatbot-frontend` (Port 3000)
- `chatbot-api` (Port 8000)
- `chatbot-postgres` (Port 5432)
- `chatbot-redis` (Port 6379)
- `chatbot-qdrant` (Port 6333)
- `chatbot-worker` (Background Celery tasks)
- `chatbot-beat` (Celery Beat periodic reconciler)

### Step 4: Verify Health & Seed Administrator
Check that all backend services and databases report healthy:
```bash
curl http://localhost:8000/api/v1/health
```
Seed the initial administrator user (configured solely by `ADMIN_EMAIL` and `ADMIN_PASSWORD` in your `.env` file):
```bash
docker compose exec api python -m scripts.seed_admin
```
*(Note: There are no default or demo credentials. You define your administrator email and password in `.env` before running the seed script.)*

### Step 5: Access Web Application
1. **Chat UI**: Navigate to [http://localhost:3000](http://localhost:3000) and log in.
2. **Admin Portal**: Navigate to [http://localhost:3000/admin](http://localhost:3000/admin) to upload knowledge base documents (e.g. from `sample_kb/`).
3. **API Documentation**: Interactive Swagger UI at [http://localhost:8000/docs](http://localhost:8000/docs) and ReDoc at [http://localhost:8000/redoc](http://localhost:8000/redoc).

---

## 4. LLM Provider Presets

The system uses a role-based LLM layer (`router` for fast classification and rewriting, `answer` for grounded generation). Preset examples in `.env`:

### Preset 1: OpenAI
```env
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
FAST_MODEL=gpt-4o-mini
ANSWER_MODEL=gpt-4o
```

### Preset 2: OpenRouter
```env
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=sk-or-...
FAST_MODEL=google/gemini-2.0-flash-001
ANSWER_MODEL=anthropic/claude-3.5-sonnet
```

### Preset 3: Google Gemini (AI Studio Free Tier)
```env
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_API_KEY=AQ...
FAST_MODEL=gemini-3.1-flash-lite
ANSWER_MODEL=gemini-3.1-flash-lite
```

### Preset 4: Anthropic (Native Messages API)
```env
LLM_PROVIDER=anthropic
LLM_BASE_URL=https://api.anthropic.com
LLM_API_KEY=sk-ant-...
FAST_MODEL=claude-3-5-haiku-20241022
ANSWER_MODEL=claude-3-5-sonnet-20241022
```

---

## 5. Supported Formats, Ingestion & Limits

| Format | Extension / Scheme | Parser Engine | Extraction Details |
|---|---|---|---|
| **PDF** | `.pdf` | `pypdf` | Page-aware extraction, preserves page numbers for citations. |
| **Word** | `.docx` | `python-docx` | Headings mapped to section metadata; paragraphs preserved. |
| **Markdown** | `.md` | `markdown_it` | AST header extraction into structured section tags. |
| **Plain Text** | `.txt` | Native UTF-8 | Clean line buffering with token chunking. |
| **Web URLs** | `http://`, `https://` | `trafilatura` + SSRF Guard | Boilerplate removal, SSRF protection against private/loopback IPs. |

### Operational Limits & Caveats
- **Maximum Upload Size**: `MAX_UPLOAD_MB=20` (rejects larger files with HTTP 413).
- **Chunk Size & Overlap**: 650 tokens per chunk with 80 tokens overlap.
- **Scanned PDFs Caveat**: Purely image-based/scanned PDFs contain no selectable text layer. By default, they yield zero extracted text unless OCR is explicitly enabled with `ENABLE_OCR=true` (requires Tesseract binaries).
- **Complex Tables Caveat**: Multi-column nested tables are flattened into sequential text lines; tabular structure is preserved best-effort.
- **SSRF Allowlist**: Ingesting web URLs requires domains to be declared in `ALLOWED_URL_DOMAINS` in `.env` (e.g. `ALLOWED_URL_DOMAINS=["example.com"]`). An empty list disables URL ingestion for security.

---

## 6. Running Tests & Evaluation

### 1. Run Automated Unit & Integration Tests
```bash
make test
# or: docker compose exec api pytest tests/ -v
```
Executes all 75 automated test suites covering authentication, lifecycle consistency, SSRF protection, LLM adapters, RAG pipeline guardrails, session memory, and retrieval latencies.

### 2. Run Threshold Calibration (`calibrate_threshold.py`)
Sweeps candidate reranking thresholds across `calibration_set.json` to find the optimal boundary between in-scope queries and out-of-scope fallbacks.
```bash
make calibrate
# or: docker compose exec api python -m eval.calibrate_threshold
```
*Architecture Rule §13: Strictly enforced prohibition prevents `calibrate_threshold.py` from ever opening `test_set.json`.*

### 3. Run Benchmark Evaluation (`run_eval.py`)
Benchmarks the live running system against `test_set.json`, testing conversation history, SSE event streams, fact checking, and an optional labeled LLM-as-judge step:
```bash
make eval
# With LLM-as-Judge enabled:
docker compose exec api python -m eval.run_eval --use-llm-judge
```

### 4. Interactive Search Inspection CLI
Test hybrid retrieval scores and cross-encoder logits for any query directly from the terminal:
```bash
docker compose exec api python -m scripts.search "What is collision resistance?"
```

---

## 7. Real Evaluation Results

The evaluation harness was run against the live system using real vector chunks from `sample_kb/` and `gemini-3.1-flash-lite`:

### A. Threshold Calibration Sweep
- **Dataset**: `eval/calibration_set.json` (in-scope collision resistance, topical out-of-scope Ethereum gas fees, unrelated beef stew recipe).
- **Score Distribution**:
  - In-Scope Query (`cal-01`): Sigmoid Score = **0.9932** (Raw Logit = +4.98)
  - Topical Out-of-Scope (`cal-02`): Sigmoid Score = **0.0010** (Raw Logit = -6.91)
  - Completely Unrelated (`cal-03`): Sigmoid Score = **0.0002** (Raw Logit = -8.51)
- **Optimal Threshold**: **`0.50`** (Precision: 100%, Recall: 100%, F1: 1.0000, Fallback Accuracy: 100%).

### B. Held-Out Evaluation Benchmark
- **Dataset**: `eval/test_set.json` (held-out direct in-scope, multi-turn follow-up with prior conversation turns, completely unrelated question).
- **Results**:
  - **Overall Accuracy**: **100.0%** (3/3 passed)
  - **Router Accuracy**: **100.0%** (Correctly routed to `SEARCH`)
  - **Answer & Facts Accuracy**: **100.0%** (All `expected_facts` grounded in text)
  - **Citation Validity**: **100.0%** (Non-empty citations with valid `[C1]` tags, source document provenance, and page numbers)
  - **Fallback Accuracy**: **100.0%** (Layer 1 safely blocked out-of-scope queries before reaching the LLM)
  - **LLM-as-Judge Verdict**: **PASS** (Model judge verified factual accuracy and absence of hallucinations)

### Honest Discussion of Failure Modes & Edge Cases
1. **Topical Adjacency**: Cross-encoder rerankers provide sharp discrimination between in-scope and out-of-scope queries (0.99 vs 0.001), but queries mentioning entities that exist in the text in an unrelated context can occasionally produce marginal scores ($0.45 \le s \le 0.55$). Layers 2 and 3 act as necessary downstream safeguards for these boundary cases.
2. **Citation Tag Format**: Citation tags must strictly follow `[C1]` format. If the prompt template allows freeform prose without bracketed tags, Layer 3 correctly flags the response as lacking verifiable citations and emits a retraction.

---

## 8. API Overview

All endpoints are versioned under `/api/v1` and document schemas using Pydantic:

| Method | Path | Access | Description |
|---|---|---|---|
| `POST` | `/api/v1/auth/register` | Public | Create user account (`role="user"` strictly enforced). |
| `POST` | `/api/v1/auth/login` | Public (Rate Limited) | Authenticate; returns access (30m) & refresh (7d) tokens. |
| `POST` | `/api/v1/auth/refresh` | Public | Refresh expired access token using refresh token. |
| `GET` | `/api/v1/auth/me` | Authenticated | Return current user profile, email, and role. |
| `POST` | `/api/v1/chat/stream` | Authenticated | Real-time SSE streaming chat (`token`, `citations`, `retract`, `error`, `done`). |
| `GET` | `/api/v1/chat/sessions` | Authenticated | List all active conversation sessions for current user. |
| `DELETE`| `/api/v1/chat/sessions/{id}`| Authenticated (Owner)| Delete conversation session and its Redis history. |
| `POST` | `/api/v1/documents` | Admin Only | Upload document (`.pdf`, `.docx`, `.md`, `.txt`) or submit URL (202 Accepted). |
| `PUT` | `/api/v1/documents/{id}` | Admin Only | Blue-green version update: upload new file version. |
| `GET` | `/api/v1/documents` | Admin Only | List all documents with status and active versions. |
| `GET` | `/api/v1/documents/{id}/status` | Admin Only | Poll document ingestion status, active version, and errors. |
| `DELETE`| `/api/v1/documents/{id}` | Admin Only | Two-phase deletion: soft delete immediately, then purge vectors. |
| `GET` | `/api/v1/health` | Public | Dependency health check (PostgreSQL, Redis, Qdrant, LLM configured). |

---

## 9. Known System Limitations

1. **Single Shared Knowledge Base**: All authenticated users query a shared repository of documents; per-tenant or per-user document isolation is not supported.
2. **Scanned Documents**: Scanned PDFs without embedded OCR layers are not indexed unless external OCR tooling is configured.
3. **Retrieval Threshold Dependency**: System grounding relies on the calibrated `RERANK_THRESHOLD`. When adding documents covering drastically different domains or vocabularies, re-running calibration is recommended.
4. **Near-Atomic Blue-Green Updates**: During new version cutover, a sub-second overlap is theoretically possible between old and new version chunks before old chunks are deactivated.