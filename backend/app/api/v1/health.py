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

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    postgres: str
    redis: str
    qdrant: str
    llm_configured: bool
    version: str = "1.0.0"


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Evaluate connectivity to critical services and check LLM configuration status."""
    pg_task = asyncio.create_task(check_postgres_health())
    redis_task = asyncio.create_task(check_redis_health())
    qdrant_task = asyncio.create_task(check_qdrant_health())

    results = await asyncio.gather(pg_task, redis_task, qdrant_task, return_exceptions=True)

    pg_healthy = results[0] is True
    redis_healthy = results[1] is True
    qdrant_healthy = results[2] is True

    all_healthy = pg_healthy and redis_healthy and qdrant_healthy
    status = "healthy" if all_healthy else "degraded"

    return HealthResponse(
        status=status,
        postgres="healthy" if pg_healthy else "unhealthy",
        redis="healthy" if redis_healthy else "unhealthy",
        qdrant="healthy" if qdrant_healthy else "unhealthy",
        llm_configured=settings.is_llm_configured(),
        version="1.0.0",
    )
