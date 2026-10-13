"""Health check endpoint.

Reports status of PostgreSQL, Redis, Qdrant, and whether an LLM is configured.
Never makes paid LLM calls.
"""
import asyncio
from fastapi import APIRouter
from pydantic import BaseModel
from app.core.config import settings
from app.db.session import check_postgres_health
from app.db.redis import check_redis_health
from app.db.qdrant import check_qdrant_health

from typing import Optional
from app.services.rag_engine import CrossEncoderSingleton
from app.services.llm.runtime import runtime_llm_manager

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    postgres: str
    redis: str
    qdrant: str
    llm_configured: bool
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    embedding_model: str
    embedding_status: str
    reranker_model: str
    reranker_status: str
    version: str = "1.0.0"


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Evaluate connectivity to critical services and check model configuration status."""
    pg_task = asyncio.create_task(check_postgres_health())
    redis_task = asyncio.create_task(check_redis_health())
    qdrant_task = asyncio.create_task(check_qdrant_health())

    results = await asyncio.gather(pg_task, redis_task, qdrant_task, return_exceptions=True)

    pg_healthy = results[0] is True
    redis_healthy = results[1] is True
    qdrant_healthy = results[2] is True

    all_healthy = pg_healthy and redis_healthy and qdrant_healthy
    status = "healthy" if all_healthy else "degraded"

    reranker_status = "ready" if CrossEncoderSingleton.is_loaded() else "configured"

    # Evaluate dynamic database LLM configuration per Prompt 7e
    runtime_config = await runtime_llm_manager.get_config()
    if runtime_config is not None:
        llm_configured = True
        llm_provider = runtime_config.active_provider_name
        llm_model = runtime_config.active_model
    else:
        llm_configured = settings.is_llm_configured()
        llm_provider = settings.LLM_PROVIDER if llm_configured else None
        llm_model = settings.ANSWER_MODEL if llm_configured else None

    return HealthResponse(
        status=status,
        postgres="healthy" if pg_healthy else "unhealthy",
        redis="healthy" if redis_healthy else "unhealthy",
        qdrant="healthy" if qdrant_healthy else "unhealthy",
        llm_configured=llm_configured,
        llm_provider=llm_provider,
        llm_model=llm_model,
        embedding_model=settings.EMBEDDING_MODEL,
        embedding_status="ready",
        reranker_model=settings.RERANKER_MODEL,
        reranker_status=reranker_status,
        version="1.0.0",
    )
