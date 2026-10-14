"""Admin System Overview & Runtime Settings API Endpoints.

Implements Prompt 7e-3: Admin System Overview (full visibility and control).
All endpoints require administrator privileges (require_admin).
Provides:
- GET /health: Health checks with per-dependency latencies
- GET /routes: Dynamic API route introspection
- GET /vector-store: Qdrant collection stats & document sync state
- GET /architecture: Live architecture parameters (read-only models + runtime settings)
- GET /workers: Celery worker & reconciler status
- GET /quality: Chat quality & grounding indicators (24h/7d aggregates, no message text)
- GET /activity: Recent admin audit trail & errors
- GET /settings: Read runtime system settings
- PUT /settings: Update runtime settings with validation & audit logging
- POST /settings/reset: Reset runtime settings to environment defaults
- GET /environment: Non-secret allowlisted environment inspection
"""
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query, status
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logger import logger
from app.core.security import require_admin
from app.db.session import get_db, AsyncSessionLocal
from app.db.redis import redis_client
from app.models.sql_models import User, Document, QueryLog, AuditLog
from app.models.schemas import (
    ErrorResponse,
    AdminSystemHealthResponse,
    DependencyHealthItem,
    SystemRoutesResponse,
    RouteInfoItem,
    VectorStoreStatsResponse,
    ArchitectureOverviewResponse,
    WorkerStatsResponse,
    ChatQualityIndicatorsResponse,
    RecentActivityResponse,
    AuditLogEntryResponse,
    SystemSettingsResponse,
    SystemSettingsUpdate,
    SystemEnvironmentResponse,
    EnvironmentSettingItem,
)
from app.services.system_settings import system_settings_manager
from app.services.llm.runtime import runtime_llm_manager
from urllib.parse import urlparse

router = APIRouter(prefix="/admin/system", tags=["admin-system"])


def _get_infra_hosts():
    """Extract host, port, and database safely without passwords."""
    try:
        db_p = urlparse(settings.DATABASE_URL.replace("postgresql+asyncpg://", "http://"))
        pg_host = db_p.hostname or "postgres"
        pg_db = db_p.path.lstrip("/") or "chatbot"
    except Exception:
        pg_host, pg_db = "postgres", "chatbot"

    try:
        r_p = urlparse(settings.REDIS_URL)
        redis_host = r_p.hostname or "redis"
        redis_port = str(r_p.port or 6379)
    except Exception:
        redis_host, redis_port = "redis", "6379"

    try:
        q_p = urlparse(settings.QDRANT_URL)
        qdrant_host = q_p.hostname or "qdrant"
        qdrant_port = str(q_p.port or 6333)
    except Exception:
        qdrant_host, qdrant_port = "qdrant", "6333"

    return pg_host, pg_db, redis_host, redis_port, qdrant_host, qdrant_port


# ==============================================================================
# 1. Health with Latencies
# ==============================================================================

@router.get(
    "/health",
    response_model=AdminSystemHealthResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Admin privileges required"},
    },
)
async def get_system_health(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> AdminSystemHealthResponse:
    """Check health and measure round-trip latencies for all system dependencies."""
    dependencies: Dict[str, DependencyHealthItem] = {}
    is_degraded = False
    is_unhealthy = False

    pg_host, pg_db, redis_host, redis_port, qdrant_host, qdrant_port = _get_infra_hosts()

    # 1. PostgreSQL
    t0 = time.perf_counter()
    try:
        await db.execute(select(1))
        pg_lat = round((time.perf_counter() - t0) * 1000.0, 2)
        dependencies["postgres"] = DependencyHealthItem(
            name="PostgreSQL",
            status="healthy" if pg_lat < 1000 else "degraded",
            latency_ms=pg_lat,
            message=f"Connected to {pg_db}",
        )
    except Exception as exc:
        pg_lat = round((time.perf_counter() - t0) * 1000.0, 2)
        is_unhealthy = True
        dependencies["postgres"] = DependencyHealthItem(
            name="PostgreSQL",
            status="unhealthy",
            latency_ms=pg_lat,
            message=f"PostgreSQL connection failed: {str(exc)}",
        )

    # 2. Redis
    t0 = time.perf_counter()
    try:
        await redis_client.ping()
        redis_lat = round((time.perf_counter() - t0) * 1000.0, 2)
        dependencies["redis"] = DependencyHealthItem(
            name="Redis",
            status="healthy" if redis_lat < 500 else "degraded",
            latency_ms=redis_lat,
            message=f"Connected to {redis_host}:{redis_port}",
        )
    except Exception as exc:
        redis_lat = round((time.perf_counter() - t0) * 1000.0, 2)
        is_unhealthy = True
        dependencies["redis"] = DependencyHealthItem(
            name="Redis",
            status="unhealthy",
            latency_ms=redis_lat,
            message=f"Redis ping failed: {str(exc)}",
        )

    # 3. Qdrant Vector Store
    t0 = time.perf_counter()
    try:
        from app.db.qdrant import get_qdrant_client
        qc = get_qdrant_client()
        qc.get_collections()
        q_lat = round((time.perf_counter() - t0) * 1000.0, 2)
        dependencies["qdrant"] = DependencyHealthItem(
            name="Qdrant",
            status="healthy" if q_lat < 1000 else "degraded",
            latency_ms=q_lat,
            message=f"Connected to collection '{settings.QDRANT_COLLECTION}'",
        )
    except Exception as exc:
        q_lat = round((time.perf_counter() - t0) * 1000.0, 2)
        is_degraded = True
        dependencies["qdrant"] = DependencyHealthItem(
            name="Qdrant",
            status="degraded",
            latency_ms=q_lat,
            message=f"Qdrant check failed: {str(exc)}",
        )

    # 4. Celery Worker Telemetry
    t0 = time.perf_counter()
    try:
        from app.workers.celery_app import celery_app
        insp = celery_app.control.inspect(timeout=0.5)
        ping_res = insp.ping() if insp else None
        c_lat = round((time.perf_counter() - t0) * 1000.0, 2)
        if ping_res:
            worker_count = len(ping_res)
            dependencies["celery"] = DependencyHealthItem(
                name="Celery",
                status="healthy",
                latency_ms=c_lat,
                message=f"{worker_count} worker(s) online",
                metadata={"workers": list(ping_res.keys())},
            )
        else:
            is_degraded = True
            dependencies["celery"] = DependencyHealthItem(
                name="Celery",
                status="degraded",
                latency_ms=c_lat,
                message="No Celery workers responded to ping (tasks queued)",
            )
    except Exception as exc:
        c_lat = round((time.perf_counter() - t0) * 1000.0, 2)
        is_degraded = True
        dependencies["celery"] = DependencyHealthItem(
            name="Celery",
            status="degraded",
            latency_ms=c_lat,
            message=f"Celery inspect error: {str(exc)}",
        )

    # 5. Active LLM Provider
    t0 = time.perf_counter()
    try:
        runtime_config = await runtime_llm_manager.get_config()
        llm_lat = round((time.perf_counter() - t0) * 1000.0, 2)
        if runtime_config and runtime_config.active_provider_name:
            dependencies["llm"] = DependencyHealthItem(
                name="LLM Provider",
                status="healthy",
                latency_ms=llm_lat,
                message=f"Active: {runtime_config.active_provider_name} ({runtime_config.active_model})",
                metadata={
                    "provider": runtime_config.active_provider_name,
                    "model": runtime_config.active_model,
                    "fallback_model": runtime_config.fallback_model,
                },
            )
        else:
            dependencies["llm"] = DependencyHealthItem(
                name="LLM Provider",
                status="healthy",
                latency_ms=llm_lat,
                message="Default environment adapter active",
            )
    except Exception as exc:
        llm_lat = round((time.perf_counter() - t0) * 1000.0, 2)
        dependencies["llm"] = DependencyHealthItem(
            name="LLM Provider",
            status="degraded",
            latency_ms=llm_lat,
            message=f"LLM runtime check warning: {str(exc)}",
        )

    overall_status = "unhealthy" if is_unhealthy else ("degraded" if is_degraded else "healthy")
    return AdminSystemHealthResponse(
        status=overall_status,
        version="1.0.0",
        checked_at=datetime.now(timezone.utc),
        dependencies=dependencies,
    )


# ==============================================================================
# 2. Dynamic Route Introspection
# ==============================================================================

@router.get(
    "/routes",
    response_model=SystemRoutesResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Admin privileges required"},
    },
)
async def get_system_routes(
    request: Request,
    admin: User = Depends(require_admin),
) -> SystemRoutesResponse:
    """Introspect all registered FastAPI application routes dynamically."""
    route_items: List[RouteInfoItem] = []
    openapi_schema = request.app.openapi()
    paths = openapi_schema.get("paths", {})

    for path, methods_dict in paths.items():
        for method_name, details in methods_dict.items():
            if method_name.lower() in ("parameters", "$ref"):
                continue

            method = method_name.upper()
            tags = details.get("tags", [])
            summary = details.get("summary", "")
            security = details.get("security", [])

            # Auth level resolution
            auth_level = "public"
            if "/admin" in path or any("admin" in str(t).lower() for t in tags):
                auth_level = "admin"
            elif security or "/sessions" in path or "/users/me" in path or "/chat/stream" in path:
                auth_level = "user"

            route_items.append(
                RouteInfoItem(
                    method=method,
                    path=path,
                    tags=tags,
                    summary=summary or None,
                    auth_level=auth_level,
                )
            )

    route_items.sort(key=lambda r: (r.path, r.method))
    base_url = str(request.base_url).rstrip("/")
    return SystemRoutesResponse(
        base_url=base_url,
        docs_url=f"{base_url}/docs",
        redoc_url=f"{base_url}/redoc",
        openapi_url=f"{base_url}/openapi.json",
        health_url=f"{base_url}/health",
        routes=route_items,
    )


# ==============================================================================
# 3. Vector Store & Collection Statistics
# ==============================================================================

@router.get(
    "/vector-store",
    response_model=VectorStoreStatsResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Admin privileges required"},
    },
)
async def get_vector_store_stats(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> VectorStoreStatsResponse:
    """Retrieve Qdrant collection status and PostgreSQL chunk/document sync statistics."""
    collection_name = settings.QDRANT_COLLECTION
    points_count = 0
    vectors_count = 0
    segments_count = 0
    coll_status = "ready"
    disk_data_size: Optional[int] = None

    try:
        from app.db.qdrant import get_qdrant_client
        qc = get_qdrant_client()
        info = qc.get_collection(collection_name)
        points_count = info.points_count or 0
        vectors_count = info.vectors_count or 0
        segments_count = info.segments_count or 0
        coll_status = str(info.status)
        if hasattr(info, "disk_data_size"):
            disk_data_size = info.disk_data_size
    except Exception as exc:
        logger.warning(f"Could not fetch full Qdrant collection stats: {exc}")
        coll_status = "unavailable"

    # Count PostgreSQL documents & versions
    active_docs_count = 0
    active_versions_count = 0
    superseded_versions_count = 0
    try:
        active_docs_res = await db.execute(
            select(func.count(Document.id)).where(Document.deleted_at.is_(None))
        )
        active_docs_count = active_docs_res.scalar() or 0

        active_ver_res = await db.execute(
            select(func.count(Document.id)).where(
                Document.deleted_at.is_(None),
                Document.status == "active",
            )
        )
        active_versions_count = active_ver_res.scalar() or 0

        superseded_res = await db.execute(
            select(func.count(Document.id)).where(
                Document.deleted_at.is_(None),
                Document.pending_version.isnot(None),
            )
        )
        superseded_versions_count = superseded_res.scalar() or 0
    except Exception as exc:
        logger.warning(f"Could not fetch PostgreSQL document stats: {exc}")

    return VectorStoreStatsResponse(
        collection_name=collection_name,
        status=coll_status,
        points_count=points_count,
        vectors_count=vectors_count,
        segments_count=segments_count,
        disk_data_size_bytes=disk_data_size,
        dense_dim=settings.EMBEDDING_DIMENSION,
        has_sparse=True,
        indexed_documents_count=active_docs_count,
        active_versions_count=active_versions_count,
        superseded_versions_count=superseded_versions_count,
    )


# ==============================================================================
# 4. Architecture & Guardrail Parameters
# ==============================================================================

@router.get(
    "/architecture",
    response_model=ArchitectureOverviewResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Admin privileges required"},
    },
)
async def get_architecture_overview(
    admin: User = Depends(require_admin),
) -> ArchitectureOverviewResponse:
    """Read live retrieval and ranking architecture parameters."""
    current_settings = await system_settings_manager.get_settings()

    return ArchitectureOverviewResponse(
        dense_model=settings.EMBEDDING_MODEL,
        dense_dim=settings.EMBEDDING_DIMENSION,
        sparse_model=settings.SPARSE_MODEL,
        fusion_method="Reciprocal Rank Fusion (RRF)",
        rrf_k=60,
        retrieval_top_k=current_settings.retrieval_top_k,
        reranker_model=settings.RERANK_MODEL,
        reranker_threshold=current_settings.reranker_threshold,
        rerank_top_n=current_settings.rerank_top_n,
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
        history_window=current_settings.history_messages,
        guardrail_layers=[
            "Layer 1: Reranker Threshold Fallback (score >= threshold)",
            "Layer 2: Streaming Sentinel Buffer Intercept",
            "Layer 3: Post-Generation Citation Grounding Verification & Retraction",
        ],
        fallback_message=settings.FALLBACK_MESSAGE,
    )


# ==============================================================================
# 5. Workers, Beat & Reconciler Status
# ==============================================================================

@router.get(
    "/workers",
    response_model=WorkerStatsResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Admin privileges required"},
    },
)
async def get_worker_stats(
    admin: User = Depends(require_admin),
) -> WorkerStatsResponse:
    """Read background Celery workers, queue length and reconciler task status."""
    online_count = 0
    worker_names: List[str] = []
    active_tasks = 0

    try:
        from app.workers.celery_app import celery_app
        insp = celery_app.control.inspect(timeout=0.5)
        if insp:
            ping_res = insp.ping() or {}
            online_count = len(ping_res)
            worker_names = list(ping_res.keys())
            active_res = insp.active() or {}
            for w, tasks in active_res.items():
                active_tasks += len(tasks)
    except Exception as exc:
        logger.warning(f"Could not inspect Celery workers: {exc}")

    # Redis queue length
    queue_len = 0
    try:
        queue_len = await redis_client.llen("celery")
    except Exception as exc:
        logger.warning(f"Could not get Celery queue length: {exc}")

    # Reconciler task telemetry
    last_rec_run: Optional[datetime] = None
    rec_fixed = 0
    rec_status = None
    try:
        raw_run = await redis_client.get("system:reconciler:last_run")
        if raw_run:
            try:
                last_rec_run = datetime.fromisoformat(raw_run.decode("utf-8") if isinstance(raw_run, bytes) else raw_run)
            except Exception:
                pass
        raw_fixed = await redis_client.get("system:reconciler:fixed_count")
        if raw_fixed:
            try:
                rec_fixed = int(raw_fixed)
            except Exception:
                pass
        raw_status = await redis_client.get("system:reconciler:status")
        if raw_status:
            rec_status = raw_status.decode("utf-8") if isinstance(raw_status, bytes) else str(raw_status)
    except Exception as exc:
        logger.warning(f"Could not fetch reconciler telemetry from Redis: {exc}")

    return WorkerStatsResponse(
        online_workers_count=online_count,
        worker_names=worker_names,
        active_tasks_count=active_tasks,
        queue_length=queue_len,
        last_beat_run=None,
        last_reconciler_run=last_rec_run,
        reconciler_fixed_count=rec_fixed,
        reconciler_last_status=rec_status,
        failed_ingestions_count=0,
    )


# ==============================================================================
# 6. Chat Quality & Grounding Indicators
# ==============================================================================

@router.get(
    "/quality",
    response_model=ChatQualityIndicatorsResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Admin privileges required"},
    },
)
async def get_chat_quality_indicators(
    window: str = Query("24h", pattern="^(24h|7d)$"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> ChatQualityIndicatorsResponse:
    """Retrieve aggregated chat quality, fallback rates and grounding metrics.

    STRICT PRIVACY: Exposes ZERO user message text or answers. Only mathematical aggregates.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=7 if window == "7d" else 1)

    stmt = select(QueryLog).where(QueryLog.created_at >= cutoff)
    res = await db.execute(stmt)
    logs = res.scalars().all()

    total_queries = len(logs)
    l1_count = sum(1 for log in logs if log.fallback_layer == 1)
    l2_count = sum(1 for log in logs if log.fallback_layer == 2)
    l3_count = sum(1 for log in logs if log.fallback_layer == 3)
    total_fallbacks = l1_count + l2_count + l3_count

    fallback_rate = round(total_fallbacks / total_queries, 4) if total_queries > 0 else 0.0

    scores = [log.top_score for log in logs if log.top_score is not None]
    avg_score = round(sum(scores) / len(scores), 4) if scores else None

    # Queries where no citations were resolved (fallback or retract)
    no_sources = sum(
        1 for log in logs
        if log.fallback_layer is not None or (log.cited_chunk_ids is not None and len(log.cited_chunk_ids) == 0)
    )

    return ChatQualityIndicatorsResponse(
        window=window,
        total_queries=total_queries,
        fallback_count=total_fallbacks,
        fallback_rate=fallback_rate,
        layer1_fallback_count=l1_count,
        layer2_fallback_count=l2_count,
        layer3_fallback_count=l3_count,
        avg_retrieval_score=avg_score,
        queries_with_no_sources=no_sources,
    )


# ==============================================================================
# 7. Recent Activity & Audit Trail
# ==============================================================================

@router.get(
    "/activity",
    response_model=RecentActivityResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Admin privileges required"},
    },
)
async def get_recent_activity(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> RecentActivityResponse:
    """Read the 20 most recent admin audit logs and recent query errors."""
    audit_stmt = select(AuditLog).order_by(desc(AuditLog.created_at)).limit(20)
    audit_res = await db.execute(audit_stmt)
    audit_rows = audit_res.scalars().all()

    # Recent query errors/retracts (last 10)
    error_stmt = (
        select(QueryLog)
        .where(QueryLog.fallback_layer == 3)
        .order_by(desc(QueryLog.created_at))
        .limit(10)
    )
    error_res = await db.execute(error_stmt)
    error_rows = error_res.scalars().all()

    recent_errors = [
        {
            "id": str(log.id),
            "timestamp": log.created_at.isoformat(),
            "type": "UNGROUNDED_RETRACT",
            "intent": log.intent,
            "fallback_layer": log.fallback_layer,
            "top_score": log.top_score,
            "threshold": log.threshold,
        }
        for log in error_rows
    ]

    return RecentActivityResponse(
        audit_logs=[AuditLogEntryResponse.model_validate(row) for row in audit_rows],
        recent_errors=recent_errors,
    )


# ==============================================================================
# 8. Runtime Settings: Read, Update, Reset
# ==============================================================================

@router.get(
    "/settings",
    response_model=SystemSettingsResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Admin privileges required"},
    },
)
async def get_system_settings(
    admin: User = Depends(require_admin),
) -> SystemSettingsResponse:
    """Read current runtime-editable system settings."""
    return await system_settings_manager.get_settings()


@router.put(
    "/settings",
    response_model=SystemSettingsResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Validation error"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Admin privileges required"},
    },
)
async def update_system_settings(
    updates: SystemSettingsUpdate,
    admin: User = Depends(require_admin),
) -> SystemSettingsResponse:
    """Update runtime system settings, bump version and notify workers."""
    return await system_settings_manager.update_settings(updates=updates, user=admin)


@router.post(
    "/settings/reset",
    response_model=SystemSettingsResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Admin privileges required"},
    },
)
async def reset_system_settings(
    admin: User = Depends(require_admin),
) -> SystemSettingsResponse:
    """Reset all runtime system settings to environment defaults."""
    return await system_settings_manager.reset_to_defaults(user=admin)


# ==============================================================================
# 9. Allowlisted Environment Inspection
# ==============================================================================

@router.get(
    "/environment",
    response_model=SystemEnvironmentResponse,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        403: {"model": ErrorResponse, "description": "Admin privileges required"},
    },
)
async def get_system_environment(
    admin: User = Depends(require_admin),
) -> SystemEnvironmentResponse:
    """Inspect safe, non-sensitive environment configuration.

    STRICT SECURITY: Uses an explicit allowlist. Never returns API keys, passwords,
    tokens, secret keys, or credentialed database connection URIs.
    """
    pg_host, pg_db, redis_host, redis_port, qdrant_host, qdrant_port = _get_infra_hosts()
    SAFE_ALLOWLIST = [
        ("APP_ENV", settings.APP_ENV, "Deployment environment (production / development / test)"),
        ("PROJECT_NAME", settings.PROJECT_NAME, "Application display title"),
        ("EMBEDDING_MODEL", settings.EMBEDDING_MODEL, "Dense embedding model (read-only)"),
        ("EMBEDDING_DIMENSION", str(settings.EMBEDDING_DIMENSION), "Vector dimensionality (read-only)"),
        ("SPARSE_MODEL", settings.SPARSE_MODEL, "Sparse tokenization / BM25 model (read-only)"),
        ("RERANK_MODEL", settings.RERANK_MODEL, "CrossEncoder reranker model (read-only)"),
        ("CHUNK_SIZE", str(settings.CHUNK_SIZE), "Document chunk size in tokens (read-only)"),
        ("CHUNK_OVERLAP", str(settings.CHUNK_OVERLAP), "Document chunk overlap in tokens (read-only)"),
        ("MAX_UPLOAD_MB", str(settings.MAX_UPLOAD_MB), "Environment default upload limit"),
        ("RATE_LIMIT_PER_MINUTE", str(settings.RATE_LIMIT_PER_MINUTE), "Environment default rate limit"),
        ("RATE_LIMIT_LOGIN_PER_MINUTE", str(settings.RATE_LIMIT_LOGIN_PER_MINUTE), "Environment default login rate limit"),
        ("SSE_KEEPALIVE_INTERVAL", str(settings.SSE_KEEPALIVE_INTERVAL), "SSE heartbeat ping interval in seconds"),
        ("POSTGRES_SERVER", pg_host, "PostgreSQL host"),
        ("POSTGRES_DB", pg_db, "PostgreSQL database name"),
        ("REDIS_HOST", redis_host, "Redis host"),
        ("REDIS_PORT", redis_port, "Redis port"),
        ("QDRANT_HOST", qdrant_host, "Qdrant vector database host"),
        ("QDRANT_PORT", qdrant_port, "Qdrant vector database port"),
        ("QDRANT_COLLECTION", settings.QDRANT_COLLECTION, "Qdrant collection name"),
    ]

    items: List[EnvironmentSettingItem] = []
    for key, val, desc in SAFE_ALLOWLIST:
        # Extra safety check: reject if key contains sensitive terms
        upper_key = key.upper()
        if any(term in upper_key for term in ["KEY", "SECRET", "PASS", "TOKEN", "CRED", "URL", "AUTH"]):
            continue
        items.append(EnvironmentSettingItem(key=key, value=str(val), description=desc))

    return SystemEnvironmentResponse(settings=items)
