---
trigger: always_on
---

# Project rules
- Always follow the architecture constraints defined here before every task: @[architecture](docs/architecture.md). It is the source of truth. If a task conflicts with it, stop and ask me.
- Stack: Python 3.11, FastAPI, SQLAlchemy 2 + Alembic, Celery + Redis, Qdrant, Loguru. Frontend: Next.js (App Router), TypeScript, Tailwind.
- All secrets and settings come from environment variables. Never hardcode keys. Keep .env.example current.
- Model names, thresholds, chunk sizes and limits live in app/core/config.py only.
- All LLM calls go through app/services/llm.py (a thin provider interface; default provider is Gemini via the google-genai SDK) so models can be swapped.
- Every task: write or update pytest tests, RUN them, and report real results. Never say something works without running it.
- Small, reviewable changes. End each task with a list of files changed and anything left unfinished. No unrelated refactors.
- Type hints everywhere, Pydantic schemas for all API input and output, docstrings on public functions.
- Never log passwords, tokens or API keys.
- Ask before adding a dependency that is not in the architecture doc.
- At the start of every task, read docs/progress.md and docs/architecture.md.
- At the end of every task, update docs/progress.md: tick finished items, add a session log entry (what was done, tests run and their real results, files changed, what is unfinished), record any deviation from the architecture, and set "Next task".
- Never mark a phase or requirement as done unless its acceptance tests were run and passed.
- If progress.md and the code disagree, say so and ask me before continuing.