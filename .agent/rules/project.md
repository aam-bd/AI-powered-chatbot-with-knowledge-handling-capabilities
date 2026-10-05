---
trigger: always_on
---

# Project rules
- At the start of every task, read docs/architecture.md @[architecture](docs/architecture.md) and docs/progress.md @[progress](docs/progress.md). architecture.md is the source of truth. If a task conflicts with it, stop and ask me.
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