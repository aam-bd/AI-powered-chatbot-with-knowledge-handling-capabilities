# AI-Powered Chatbot with Knowledge Handling Capabilities

An enterprise-grade Knowledge-Base (KB) RAG chatbot that answers questions **only** from a custom knowledge base of documents with strict hallucination guards and verified source citations.

---

## Architecture Overview

- **Frontend:** Next.js (App Router), TypeScript, Tailwind CSS
- **API Server:** FastAPI (Python 3.11), Loguru JSON logging, Request-ID tracing
- **Workers:** Celery with Redis broker (ingestion, reconciliation, two-phase deletion)
- **Primary Database:** PostgreSQL 15 (SQLAlchemy 2, Alembic)
- **Vector Database:** Qdrant (dense `BAAI/bge-m3` + sparse BM25 vectors)
- **Reranker:** `BAAI/bge-reranker-v2-m3` (cross-encoder)
- **LLM Support:** Provider-agnostic (OpenAI, OpenRouter, Google Gemini, Anthropic, Ollama, vLLM)

---

## Project Structure

```text
├── frontend/             # Next.js frontend application
├── backend/              # FastAPI application, Celery workers, evaluation suite
│   ├── app/
│   │   ├── api/          # REST endpoints (/api/v1) & SSE stream
│   │   ├── core/         # Settings, logging, security, rate limiting
│   │   ├── db/           # PostgreSQL, Redis, Qdrant database clients
│   │   ├── models/       # SQLAlchemy models & Pydantic schemas
│   │   ├── services/     # RAG engine, LLM adapters, parsers, memory
│   │   └── workers/      # Celery task definitions
│   ├── scripts/          # Admin seeding, search inspection, re-indexing
│   ├── eval/             # Calibration & test datasets, evaluation scripts
│   └── tests/            # Automated test suite
├── sample_kb/            # Reference knowledge base documents
├── docs/                 # Architecture, progress log, decisions log
├── docker-compose.yml    # Complete local container orchestration
└── Makefile              # Task automation shortcuts
```

---

## Getting Started

1. Copy the environment configuration:
   ```bash
   cp .env.example .env
   ```
2. Start the services using Docker Compose:
   ```bash
   make up
   # or: docker compose up -d --build
   ```
3. Check service health:
   ```bash
   curl http://localhost:8000/api/v1/health
   ```
4. Access API documentation:
   - Interactive Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
   - Alternative ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)