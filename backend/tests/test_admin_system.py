"""Acceptance and unit tests for Prompt 7e-3: Admin System Overview & Settings.

Covers:
1. test_non_admin_forbidden_on_all_system_endpoints: 401 unauthenticated, 403 regular user.
2. test_system_health_latencies_and_status: Per-dependency latency check (Postgres, Redis, Qdrant, Celery, LLM).
3. test_routes_introspection: Inspects FastAPI routes and correct auth_level detection.
4. test_vector_store_stats: Qdrant collection statistics and PostgreSQL document counts.
5. test_architecture_overview: Read-only model parameters and dynamic settings.
6. test_worker_and_reconciler_stats: Celery worker ping, queue length, reconciler status.
7. test_chat_quality_indicators_aggregated_without_pii: Mathematical aggregates with zero message text.
8. test_system_settings_read_and_update_validation: Range bounds and invariant rerank_top_n <= retrieval_top_k.
9. test_grounding_warning_when_threshold_lowered: Audit log records grounding_warning when threshold < 0.5.
10. test_reset_to_defaults: Resets settings to environment defaults and logs audit record.
11. test_environment_safe_allowlist_never_leaks_secrets: Explicit allowlist only, zero passwords or tokens.
"""
import uuid
import asyncio
import pytest
from starlette.testclient import TestClient
from sqlalchemy import select, desc

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.sql_models import User, AuditLog, QueryLog
from app.services.system_settings import system_settings_manager


def _get_auth_headers(client: TestClient, role: str = "admin") -> dict:
    """Helper to create and log in a user with a given role, returning Authorization headers."""
    uid = uuid.uuid4().hex[:8]
    email = f"{role}_{uid}@example.com"
    password = "StrongTestPassword123!"

    reg_resp = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert reg_resp.status_code == 201
    user_id = reg_resp.json()["id"]

    if role == "admin":
        async def _make_admin():
            async with AsyncSessionLocal() as db:
                res = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
                db_user = res.scalar_one()
                db_user.role = "admin"
                db_user.is_active = True
                await db.commit()
        asyncio.run(_make_admin())

    login_resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


SYSTEM_ENDPOINTS = [
    ("GET", "/api/v1/admin/system/health"),
    ("GET", "/api/v1/admin/system/routes"),
    ("GET", "/api/v1/admin/system/vector-store"),
    ("GET", "/api/v1/admin/system/architecture"),
    ("GET", "/api/v1/admin/system/workers"),
    ("GET", "/api/v1/admin/system/quality"),
    ("GET", "/api/v1/admin/system/activity"),
    ("GET", "/api/v1/admin/system/settings"),
    ("PUT", "/api/v1/admin/system/settings"),
    ("POST", "/api/v1/admin/system/settings/reset"),
    ("GET", "/api/v1/admin/system/environment"),
]


def test_non_admin_forbidden_on_all_system_endpoints(client: TestClient):
    """Anonymous gets 401; non-admin user gets 403 on all /admin/system/* endpoints."""
    user_headers = _get_auth_headers(client, role="user")

    for method, path in SYSTEM_ENDPOINTS:
        # 1. Unauthenticated -> 401
        if method == "GET":
            r_anon = client.get(path)
        elif method == "PUT":
            r_anon = client.put(path, json={})
        elif method == "POST":
            r_anon = client.post(path)
        assert r_anon.status_code == 401, f"Expected 401 for anon on {method} {path}, got {r_anon.status_code}"

        # 2. Regular user -> 403
        if method == "GET":
            r_user = client.get(path, headers=user_headers)
        elif method == "PUT":
            r_user = client.put(path, json={}, headers=user_headers)
        elif method == "POST":
            r_user = client.post(path, headers=user_headers)
        assert r_user.status_code == 403, f"Expected 403 for user on {method} {path}, got {r_user.status_code}"


def test_system_health_latencies_and_status(client: TestClient):
    """Admin health check returns per-dependency latencies and overall status."""
    admin_headers = _get_auth_headers(client, role="admin")
    resp = client.get("/api/v1/admin/system/health", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] in ("healthy", "degraded", "unhealthy")
    assert "checked_at" in data
    deps = data["dependencies"]
    assert "postgres" in deps
    assert "redis" in deps
    assert "qdrant" in deps
    assert "celery" in deps
    assert "llm" in deps

    # Per-dependency latencies
    assert isinstance(deps["postgres"]["latency_ms"], (int, float))
    assert deps["postgres"]["status"] in ("healthy", "degraded", "unhealthy")
    assert isinstance(deps["redis"]["latency_ms"], (int, float))
    assert deps["redis"]["status"] in ("healthy", "degraded", "unhealthy")


def test_routes_introspection(client: TestClient):
    """Dynamic route introspection lists registered API routes with auth levels."""
    admin_headers = _get_auth_headers(client, role="admin")
    resp = client.get("/api/v1/admin/system/routes", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert "routes" in data
    routes = data["routes"]
    assert len(routes) > 10

    paths = [r["path"] for r in routes]
    assert "/api/v1/chat/stream" in paths
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/admin/system/health" in paths

    # Verify auth_level detection
    for r in routes:
        if "/admin" in r["path"]:
            assert r["auth_level"] == "admin"


def test_vector_store_stats(client: TestClient):
    """Vector store stats endpoint returns collection info and synced doc counts."""
    admin_headers = _get_auth_headers(client, role="admin")
    resp = client.get("/api/v1/admin/system/vector-store", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["collection_name"] == settings.QDRANT_COLLECTION
    assert data["dense_dim"] == settings.EMBEDDING_DIMENSION
    assert data["has_sparse"] is True
    assert isinstance(data["points_count"], int)
    assert isinstance(data["indexed_documents_count"], int)


def test_architecture_overview(client: TestClient):
    """Architecture overview endpoint returns read-only and runtime parameters."""
    admin_headers = _get_auth_headers(client, role="admin")
    resp = client.get("/api/v1/admin/system/architecture", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["dense_model"] == settings.EMBEDDING_MODEL
    assert data["dense_dim"] == settings.EMBEDDING_DIMENSION
    assert data["sparse_model"] == settings.SPARSE_MODEL
    assert data["reranker_model"] == settings.RERANK_MODEL
    assert data["chunk_size"] == settings.CHUNK_SIZE
    assert data["chunk_overlap"] == settings.CHUNK_OVERLAP
    assert len(data["guardrail_layers"]) == 3
    assert "reranker_threshold" in data


def test_worker_and_reconciler_stats(client: TestClient):
    """Worker stats returns worker counts, queue lengths, and reconciler status."""
    admin_headers = _get_auth_headers(client, role="admin")
    resp = client.get("/api/v1/admin/system/workers", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert isinstance(data["online_workers_count"], int)
    assert isinstance(data["queue_length"], int)
    assert isinstance(data["reconciler_fixed_count"], int)


def test_chat_quality_indicators_aggregated_without_pii(client: TestClient):
    """Chat quality indicators return mathematical aggregates with zero user message text."""
    admin_headers = _get_auth_headers(client, role="admin")

    # Insert a synthetic query log entry to test aggregation
    async def _insert_query_log():
        async with AsyncSessionLocal() as session:
            ql = QueryLog(
                user_id=None,
                session_id=str(uuid.uuid4()),
                intent="SEARCH",
                original_query="What is the reimbursement limit?",
                top_score=0.42,
                threshold=0.50,
                fallback_layer=1,
            )
            session.add(ql)
            await session.commit()
    asyncio.run(_insert_query_log())

    resp = client.get("/api/v1/admin/system/quality?window=24h", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["window"] == "24h"
    assert data["total_queries"] >= 1
    assert data["fallback_count"] >= 1
    assert "avg_retrieval_score" in data

    # Verify no PII fields in schema
    raw_text = resp.text
    assert "reimbursement" not in raw_text


def test_system_settings_read_and_update_validation(client: TestClient):
    """Admin can read and update runtime settings; invalid inputs are rejected."""
    admin_headers = _get_auth_headers(client, role="admin")

    # Read current settings
    get_resp = client.get("/api/v1/admin/system/settings", headers=admin_headers)
    assert get_resp.status_code == 200
    initial_version = get_resp.json()["version"]

    # Valid update
    update_resp = client.put(
        "/api/v1/admin/system/settings",
        json={"retrieval_top_k": 20, "rerank_top_n": 5, "reranker_threshold": 0.60},
        headers=admin_headers,
    )
    assert update_resp.status_code == 200
    updated_data = update_resp.json()
    assert updated_data["retrieval_top_k"] == 20
    assert updated_data["rerank_top_n"] == 5
    assert updated_data["reranker_threshold"] == 0.60
    assert updated_data["version"] > initial_version

    # Invalid: rerank_top_n > retrieval_top_k -> 422
    inv_resp = client.put(
        "/api/v1/admin/system/settings",
        json={"retrieval_top_k": 5, "rerank_top_n": 10},
        headers=admin_headers,
    )
    assert inv_resp.status_code == 422

    # Invalid: out of bounds threshold (0.05 < 0.20)
    oob_resp = client.put(
        "/api/v1/admin/system/settings",
        json={"reranker_threshold": 0.05},
        headers=admin_headers,
    )
    assert oob_resp.status_code == 422


def test_grounding_warning_when_threshold_lowered(client: TestClient):
    """Lowering reranker_threshold < 0.5 triggers grounding_warning in audit log."""
    admin_headers = _get_auth_headers(client, role="admin")

    # Update threshold to 0.40 (< 0.50)
    resp = client.put(
        "/api/v1/admin/system/settings",
        json={"reranker_threshold": 0.40},
        headers=admin_headers,
    )
    assert resp.status_code == 200

    # Verify audit log captures grounding warning
    async def _check_audit_log():
        async with AsyncSessionLocal() as session:
            stmt = (
                select(AuditLog)
                .where(AuditLog.action == "UPDATE_SYSTEM_SETTINGS")
                .order_by(desc(AuditLog.created_at))
                .limit(1)
            )
            res = await session.execute(stmt)
            log_entry = res.scalar_one()
            assert log_entry.details.get("grounding_warning") is True
    asyncio.run(_check_audit_log())


def test_reset_to_defaults(client: TestClient):
    """Admin can reset runtime settings to environment defaults."""
    admin_headers = _get_auth_headers(client, role="admin")

    # Change setting first
    client.put("/api/v1/admin/system/settings", json={"retrieval_top_k": 30}, headers=admin_headers)

    # Call reset
    resp = client.post("/api/v1/admin/system/settings/reset", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["retrieval_top_k"] == 15
    assert data["reranker_threshold"] == 0.50


def test_environment_safe_allowlist_never_leaks_secrets(client: TestClient):
    """Environment inspection only returns allowlisted keys and never leaks secrets."""
    admin_headers = _get_auth_headers(client, role="admin")
    resp = client.get("/api/v1/admin/system/environment", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert "settings" in data
    settings_list = data["settings"]
    keys = [item["key"] for item in settings_list]

    # Verify safe keys exist
    assert "APP_ENV" in keys
    assert "PROJECT_NAME" in keys
    assert "EMBEDDING_MODEL" in keys
    assert "QDRANT_COLLECTION" in keys

    # Verify NO secrets leaked
    forbidden = ["KEY", "SECRET", "PASS", "TOKEN", "CREDENTIAL", "DATABASE_URL"]
    for item in settings_list:
        upper_k = item["key"].upper()
        for f in forbidden:
            assert f not in upper_k, f"Forbidden substring '{f}' found in environment key '{item['key']}'"
        assert "postgresql://" not in item["value"], "Database connection string leaked!"
        assert "@" not in item["value"], "Potential credentialed URI leaked!"
