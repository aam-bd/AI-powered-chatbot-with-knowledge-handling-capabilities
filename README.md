# AI-powered-chatbot-with-knowledge-handling-capabilities
An enterprise-grade RAG chatbot that delivers accurate, context-aware answers strictly from a custom knowledge base. It features hybrid search, session memory, verified source citations, and zero-downtime document updates. Built with strict hallucination guards, the system gracefully handles out-of-scope queries to guarantee reliability.

Project initialized. 

ai-chatbot-project/
├── frontend/src/
│   ├── components/ (ChatWindow, CitationsDrawer, AdminDocManager, SessionControls, LoginForm)
│   └── services/ (api.ts, streamChat.ts)
├── backend/
│   ├── app/
│   │   ├── api/v1/ (auth, chat, documents, health) + router.py
│   │   ├── core/ (config, security, logger, rate_limit)
│   │   ├── db/ (session, redis, qdrant) + migrations/ (Alembic)
│   │   ├── models/ (sql_models, schemas)
│   │   ├── services/
│   │   │   ├── intent_router.py
│   │   │   ├── rag_engine.py
│   │   │   ├── citation_service.py
│   │   │   ├── session_manager.py
│   │   │   └── parsers/ (pdf, docx, markdown, text, web)
│   │   ├── workers/ (celery_app, tasks_ingestion, tasks_deletion, tasks_reconcile)
│   │   └── main.py
│   ├── scripts/seed_admin.py
│   ├── tests/ (test_auth, test_rag_pipeline, test_lifecycle_consistency, test_ssrf)
│   ├── eval/ (calibration_set.json, test_set.json, calibrate_threshold.py, run_eval.py)
│   ├── requirements.txt
│   └── Dockerfile
├── sample_kb/                  # demo documents
├── docker-compose.yml          # api, worker, frontend, postgres, redis, qdrant
└── README.md