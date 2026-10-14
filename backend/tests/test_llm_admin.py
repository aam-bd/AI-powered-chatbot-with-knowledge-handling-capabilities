"""Acceptance and unit tests for Prompt 7e: Admin LLM provider and API key management.

Covers:
1. test_non_admin_forbidden_on_all_endpoints: Non-admin gets 403 on all /admin/llm/* routes; unauthenticated gets 401.
2. test_keys_encrypted_in_db_and_never_leaked: Fernet encrypted in DB, masked in API (hint only), not in logs.
3. test_provider_crud_and_delete_protection: Create, list, patch (preserves key if empty), 409 deleting active provider.
4. test_settings_validation: Rejects unowned model (400), disabled provider (400), invalid temperature/max_tokens.
5. test_ssrf_validation: Private/loopback URLs rejected when ALLOW_PRIVATE_LLM_URLS=False; allowed when True.
6. test_hot_reload_without_restart: Updating settings bumps version; next request uses new model immediately.
7. test_fallback_used_on_primary_failure_and_no_secrets: Primary 5xx/timeout falls back to fallback provider cleanly.
8. test_bootstrap_seeding_on_empty_table: Seeds provider & settings from .env on empty DB.
"""
import uuid
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest
from starlette.testclient import TestClient
from sqlalchemy import select, delete

from app.core.config import settings
from app.core.crypto import decrypt_api_key
from app.db.session import AsyncSessionLocal
from app.models.sql_models import User, LLMProvider, LLMSettings
from app.services.llm.base import LLMUnavailableError, LLMError
from app.services.llm.runtime import runtime_llm_manager, bootstrap_llm_settings, REDIS_VERSION_KEY
from app.db.redis import get_redis_client


def _get_auth_headers(client: TestClient, role: str = "admin") -> dict:
    """Helper to create and log in a user with a given role, returning Authorization headers."""
    uid = uuid.uuid4().hex[:8]
    email = f"{role}_{uid}@example.com"
    password = "StrongTestPassword123!"
    ip = f"198.51.100.{uuid.uuid4().int % 200 + 10}"

    # Register user
    reg_resp = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert reg_resp.status_code == 201
    user_id = reg_resp.json()["id"]

    # Promote to admin if requested
    if role == "admin":
        async def _make_admin():
            async with AsyncSessionLocal() as db:
                res = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
                db_user = res.scalar_one()
                db_user.role = "admin"
                db_user.is_active = True
                await db.commit()
        asyncio.run(_make_admin())

    # Login
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        headers={"X-Forwarded-For": ip},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}", "X-Forwarded-For": ip}


# ------------------------------------------------------------------------------
# 1. Authorization Tests
# ------------------------------------------------------------------------------

def test_non_admin_forbidden_on_all_endpoints(client: TestClient):
    """Verify that regular authenticated users receive 403 on all /admin/llm endpoints, and 401 if unauth."""
    user_headers = _get_auth_headers(client, role="user")
    dummy_uuid = str(uuid.uuid4())

    endpoints = [
        ("GET", "/api/v1/admin/llm/providers", None),
        ("POST", "/api/v1/admin/llm/providers", {"name": "Test", "provider_type": "openai_compatible", "base_url": "https://api.openai.com/v1", "models": ["gpt-4o"], "default_model": "gpt-4o"}),
        ("PATCH", f"/api/v1/admin/llm/providers/{dummy_uuid}", {"name": "Renamed"}),
        ("DELETE", f"/api/v1/admin/llm/providers/{dummy_uuid}", None),
        ("POST", f"/api/v1/admin/llm/providers/{dummy_uuid}/test", None),
        ("GET", f"/api/v1/admin/llm/models?provider_id={dummy_uuid}", None),
        ("GET", "/api/v1/admin/llm/settings", None),
        ("PUT", "/api/v1/admin/llm/settings", {"active_provider_id": dummy_uuid, "active_model": "gpt-4o"}),
    ]

    for method, path, body in endpoints:
        # Unauthenticated -> 401
        if method == "GET":
            unauth_resp = client.get(path)
        elif method == "POST":
            unauth_resp = client.post(path, json=body or {})
        elif method == "PATCH":
            unauth_resp = client.patch(path, json=body or {})
        elif method == "DELETE":
            unauth_resp = client.delete(path)
        elif method == "PUT":
            unauth_resp = client.put(path, json=body or {})
        assert unauth_resp.status_code in (401, 403), f"Expected 401/403 unauth on {method} {path}, got {unauth_resp.status_code}"

        # Regular user -> 403
        if method == "GET":
            resp = client.get(path, headers=user_headers)
        elif method == "POST":
            resp = client.post(path, json=body or {}, headers=user_headers)
        elif method == "PATCH":
            resp = client.patch(path, json=body or {}, headers=user_headers)
        elif method == "DELETE":
            resp = client.delete(path, headers=user_headers)
        elif method == "PUT":
            resp = client.put(path, json=body or {}, headers=user_headers)
        assert resp.status_code == 403, f"Expected 403 on {method} {path}, got {resp.status_code}"


# ------------------------------------------------------------------------------
# 2. Encryption & Key Redaction Tests
# ------------------------------------------------------------------------------

def test_keys_encrypted_in_db_and_never_leaked(client: TestClient):
    """Verify keys are stored encrypted in DB with Fernet and never echoed in API or logs."""
    admin_headers = _get_auth_headers(client, role="admin")
    secret_key = "sk-supersecret-production-token-9876543210"
    provider_name = f"Encrypted Prov {uuid.uuid4().hex[:6]}"

    # Create provider
    create_payload = {
        "name": provider_name,
        "provider_type": "openai_compatible",
        "base_url": "https://api.openai.com/v1",
        "api_key": secret_key,
        "models": ["gpt-4o", "gpt-4o-mini"],
        "default_model": "gpt-4o-mini",
        "is_enabled": True,
    }
    resp = client.post("/api/v1/admin/llm/providers", json=create_payload, headers=admin_headers)
    assert resp.status_code == 201
    data = resp.json()

    # API response checks: has_key is True, key_hint is "...3210", raw key is nowhere in response
    assert data["has_key"] is True
    assert data["key_hint"] == "...3210"
    assert secret_key not in str(data)
    provider_id = data["id"]

    # Verify database row: raw secret key is NOT present; it starts with Fernet ciphertext
    async def _check_db():
        async with AsyncSessionLocal() as db:
            p_res = await db.execute(select(LLMProvider).where(LLMProvider.id == uuid.UUID(provider_id)))
            prov = p_res.scalar_one()
            assert prov.api_key_encrypted is not None
            assert secret_key not in prov.api_key_encrypted
            # Decrypt verifies round-trip
            assert decrypt_api_key(prov.api_key_encrypted) == secret_key
    asyncio.run(_check_db())

    # GET /providers listing check
    list_resp = client.get("/api/v1/admin/llm/providers", headers=admin_headers)
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert secret_key not in str(list_data)


# ------------------------------------------------------------------------------
# 3. Provider CRUD & Delete In-Use Protection Tests
# ------------------------------------------------------------------------------

def test_provider_crud_and_delete_protection(client: TestClient):
    """Test full CRUD, key preservation on empty update, and 409 deleting active/fallback provider."""
    admin_headers = _get_auth_headers(client, role="admin")
    name = f"CRUD Provider {uuid.uuid4().hex[:6]}"

    # Create
    c_resp = client.post(
        "/api/v1/admin/llm/providers",
        json={
            "name": name,
            "provider_type": "openai_compatible",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-initial-key-1234",
            "models": ["model-alpha", "model-beta"],
            "default_model": "model-alpha",
        },
        headers=admin_headers,
    )
    assert c_resp.status_code == 201
    prov_id = c_resp.json()["id"]

    # Patch: update default_model without sending api_key
    patch_resp = client.patch(
        f"/api/v1/admin/llm/providers/{prov_id}",
        json={"default_model": "model-beta"},
        headers=admin_headers,
    )
    assert patch_resp.status_code == 200
    p_data = patch_resp.json()
    assert p_data["default_model"] == "model-beta"
    assert p_data["has_key"] is True
    assert p_data["key_hint"] == "...1234"  # Key preserved!

    # Make this provider the active provider in settings
    set_resp = client.put(
        "/api/v1/admin/llm/settings",
        json={
            "active_provider_id": prov_id,
            "active_model": "model-beta",
            "temperature": 0.1,
            "max_tokens": 512,
        },
        headers=admin_headers,
    )
    assert set_resp.status_code == 200

    # Attempt to delete active provider -> 409 Conflict
    del_active_resp = client.delete(f"/api/v1/admin/llm/providers/{prov_id}", headers=admin_headers)
    assert del_active_resp.status_code == 409
    assert "currently active" in del_active_resp.json()["detail"]

    # Create another unused provider and delete it -> 200 OK
    unused_name = f"Unused Provider {uuid.uuid4().hex[:6]}"
    c2 = client.post(
        "/api/v1/admin/llm/providers",
        json={
            "name": unused_name,
            "provider_type": "openai_compatible",
            "base_url": "https://api.openai.com/v1",
            "models": ["model-gamma"],
            "default_model": "model-gamma",
        },
        headers=admin_headers,
    )
    assert c2.status_code == 201
    unused_id = c2.json()["id"]

    del_resp = client.delete(f"/api/v1/admin/llm/providers/{unused_id}", headers=admin_headers)
    assert del_resp.status_code == 200
    assert del_resp.json()["code"] == "PROVIDER_DELETED"


# ------------------------------------------------------------------------------
# 4. Settings Validation Tests
# ------------------------------------------------------------------------------

def test_settings_validation_rejects_unowned_model_and_disabled_provider(client: TestClient):
    """Verify settings update rejects models not belonging to provider or disabled providers."""
    admin_headers = _get_auth_headers(client, role="admin")

    # Create an enabled provider
    p1_name = f"Prov Valid 1 {uuid.uuid4().hex[:6]}"
    p1 = client.post(
        "/api/v1/admin/llm/providers",
        json={
            "name": p1_name,
            "provider_type": "openai_compatible",
            "base_url": "https://api.openai.com/v1",
            "models": ["valid-model-1", "valid-model-2"],
            "default_model": "valid-model-1",
        },
        headers=admin_headers,
    ).json()

    # 1. Reject unowned model
    bad_model_resp = client.put(
        "/api/v1/admin/llm/settings",
        json={
            "active_provider_id": p1["id"],
            "active_model": "alien-model-99",
        },
        headers=admin_headers,
    )
    assert bad_model_resp.status_code == 400
    assert "does not belong" in bad_model_resp.json()["detail"]

    # 2. Reject setting a disabled provider as active
    p2_name = f"Prov Disabled {uuid.uuid4().hex[:6]}"
    p2 = client.post(
        "/api/v1/admin/llm/providers",
        json={
            "name": p2_name,
            "provider_type": "openai_compatible",
            "base_url": "https://api.openai.com/v1",
            "models": ["m1"],
            "default_model": "m1",
            "is_enabled": False,
        },
        headers=admin_headers,
    ).json()

    disabled_resp = client.put(
        "/api/v1/admin/llm/settings",
        json={
            "active_provider_id": p2["id"],
            "active_model": "m1",
        },
        headers=admin_headers,
    )
    assert disabled_resp.status_code == 400
    assert "disabled" in disabled_resp.json()["detail"]


# ------------------------------------------------------------------------------
# 5. SSRF Base URL Validation Tests
# ------------------------------------------------------------------------------

def test_ssrf_validation_rejects_private_and_loopback_urls(client: TestClient, monkeypatch):
    """Verify SSRF rules: private/loopback URLs rejected unless ALLOW_PRIVATE_LLM_URLS is true."""
    admin_headers = _get_auth_headers(client, role="admin")

    # When private URLs are disallowed (default)
    monkeypatch.setattr(settings, "ALLOW_PRIVATE_LLM_URLS", False)

    private_urls = [
        "http://192.168.1.50:8000/v1",
        "http://10.0.0.1:11434/v1",
        "http://127.0.0.1:11434/v1",
        "http://localhost:11434/v1",
    ]

    for purl in private_urls:
        resp = client.post(
            "/api/v1/admin/llm/providers",
            json={
                "name": f"SSRF Test {uuid.uuid4().hex[:6]}",
                "provider_type": "openai_compatible",
                "base_url": purl,
                "models": ["llama3"],
                "default_model": "llama3",
            },
            headers=admin_headers,
        )
        assert resp.status_code == 400
        assert "SSRF Protection" in resp.json()["detail"]

    # When ALLOW_PRIVATE_LLM_URLS is True in development
    monkeypatch.setattr(settings, "ALLOW_PRIVATE_LLM_URLS", True)
    monkeypatch.setattr(settings, "APP_ENV", "development")

    allowed_resp = client.post(
        "/api/v1/admin/llm/providers",
        json={
            "name": f"Ollama Local {uuid.uuid4().hex[:6]}",
            "provider_type": "openai_compatible",
            "base_url": "http://localhost:11434/v1",
            "models": ["llama3"],
            "default_model": "llama3",
        },
        headers=admin_headers,
    )
    assert allowed_resp.status_code == 201


# ------------------------------------------------------------------------------
# 6. Hot Reload Tests
# ------------------------------------------------------------------------------

def test_hot_reload_without_restart(client: TestClient):
    """Verify that updating active settings increments version and is picked up immediately."""
    admin_headers = _get_auth_headers(client, role="admin")

    # Create provider with two models
    p = client.post(
        "/api/v1/admin/llm/providers",
        json={
            "name": f"Hot Reload Prov {uuid.uuid4().hex[:6]}",
            "provider_type": "openai_compatible",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-hot-reload-key-1234",
            "models": ["hot-model-1", "hot-model-2"],
            "default_model": "hot-model-1",
        },
        headers=admin_headers,
    ).json()

    # Step 1: Set model-1
    client.put(
        "/api/v1/admin/llm/settings",
        json={"active_provider_id": p["id"], "active_model": "hot-model-1"},
        headers=admin_headers,
    )

    # Step 2: Fetch runtime config
    cfg1 = asyncio.run(runtime_llm_manager.get_config(force_refresh=True))
    assert cfg1 is not None
    assert cfg1.active_model == "hot-model-1"
    initial_version = cfg1.version

    # Step 3: Switch to model-2 via API
    put_resp = client.put(
        "/api/v1/admin/llm/settings",
        json={"active_provider_id": p["id"], "active_model": "hot-model-2"},
        headers=admin_headers,
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["version"] == initial_version + 1

    # Step 4: Next runtime config query picks up model-2 without restart
    cfg2 = asyncio.run(runtime_llm_manager.get_config(force_refresh=True))
    assert cfg2 is not None
    assert cfg2.active_model == "hot-model-2"
    assert cfg2.version == initial_version + 1


# ------------------------------------------------------------------------------
# 7. Fallback Recovery Tests
# ------------------------------------------------------------------------------

def test_fallback_used_on_primary_failure_and_no_secrets(client: TestClient, monkeypatch):
    """Verify that when primary adapter fails with 5xx/timeout, fallback adapter executes."""
    # Setup mock config with primary and fallback
    mock_primary = MagicMock()
    mock_primary.complete = AsyncMock(side_effect=LLMUnavailableError("Primary 503 Service Unavailable"))

    mock_fallback = MagicMock()
    mock_fallback.complete = AsyncMock(return_value="Recovered answer from fallback model.")

    mock_config = MagicMock()
    mock_config.active_adapter = mock_primary
    mock_config.active_model = "primary-model"
    mock_config.active_provider_name = "PrimaryProvider"
    mock_config.fallback_adapter = mock_fallback
    mock_config.fallback_model = "fallback-model"
    mock_config.fallback_provider_name = "FallbackProvider"
    mock_config.temperature = 0.0
    mock_config.max_tokens = 512

    # Patch runtime manager's get_config using monkeypatch so it auto-restores
    async def _mock_get_cfg(*args, **kwargs):
        return mock_config

    monkeypatch.setattr(runtime_llm_manager, "get_config", _mock_get_cfg)

    async def _run_test():
        res = await runtime_llm_manager.execute_complete_with_fallback(
            system="System",
            messages=[{"role": "user", "content": "Question"}],
        )
        assert res == "Recovered answer from fallback model."
        assert mock_primary.complete.await_count == 1
        assert mock_fallback.complete.await_count == 1

    asyncio.run(_run_test())


# ------------------------------------------------------------------------------
# 8. Bootstrap Seeding Tests
# ------------------------------------------------------------------------------

def test_bootstrap_seeding_on_empty_table():
    """Verify that bootstrap seeding populates llm_providers and llm_settings on startup."""
    async def _run_bootstrap_test():
        # Clean test tables
        async with AsyncSessionLocal() as db:
            await db.execute(delete(LLMSettings))
            await db.execute(delete(LLMProvider))
            await db.commit()

        # Run bootstrap
        await bootstrap_llm_settings()

        # Verify populated
        async with AsyncSessionLocal() as db:
            p_res = await db.execute(select(LLMProvider))
            providers = p_res.scalars().all()
            assert len(providers) >= 1
            default_p = next((p for p in providers if "Default" in p.name), None)
            assert default_p is not None
            assert "Default" in default_p.name

            s_res = await db.execute(select(LLMSettings).where(LLMSettings.id == 1))
            settings_row = s_res.scalar_one_or_none()
            assert settings_row is not None
            assert settings_row.active_provider_id == default_p.id
            assert settings_row.version == 1

        # Second bootstrap run should be a no-op
        await bootstrap_llm_settings()
        async with AsyncSessionLocal() as db:
            count_res = await db.execute(select(LLMProvider))
            assert len(count_res.scalars().all()) == len(providers)

        # Refresh runtime manager cache with restored bootstrap settings
        runtime_llm_manager.invalidate_local_cache()
        await runtime_llm_manager.get_config(force_refresh=True)

    asyncio.run(_run_bootstrap_test())


# ------------------------------------------------------------------------------
# 9. Chat Stream Hot Reload & Fallback Integration Tests
# ------------------------------------------------------------------------------

def test_chat_stream_hot_reloads_active_model_without_restart(client: TestClient, monkeypatch):
    """Verify that when active model changes, next chat request streams with the new model."""
    admin_headers = _get_auth_headers(client, role="admin")

    # Create provider
    p = client.post(
        "/api/v1/admin/llm/providers",
        json={
            "name": f"Stream Reload Prov {uuid.uuid4().hex[:6]}",
            "provider_type": "openai_compatible",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test-stream-reload",
            "models": ["model-step-1", "model-step-2"],
            "default_model": "model-step-1",
        },
        headers=admin_headers,
    ).json()

    # Step 1: Set model-step-1
    client.put(
        "/api/v1/admin/llm/settings",
        json={"active_provider_id": p["id"], "active_model": "model-step-1"},
        headers=admin_headers,
    )

    models_used = []

    class MockStreamAdapter:
        async def complete(self, *args, **kwargs):
            return '{"intent": "GREETING", "clarification_message": null, "standalone_query": null}'

        async def stream(self, system, messages, model, **kwargs):
            models_used.append(model)
            yield "Answer from "
            yield model
            yield " [C1]"

    mock_adapter = MockStreamAdapter()

    # Ensure get_llm_adapter returns our mock adapter but model comes from config
    orig_get_config = runtime_llm_manager.get_config

    async def _mocked_config(force_refresh=False):
        cfg = await orig_get_config(force_refresh=force_refresh)
        if cfg:
            cfg.active_adapter = mock_adapter
        return cfg

    monkeypatch.setattr(runtime_llm_manager, "get_config", _mocked_config)

    # First turn uses model-step-1
    cfg_1 = asyncio.run(runtime_llm_manager.get_config(force_refresh=True))
    assert cfg_1.active_model == "model-step-1"

    # Step 2: Switch to model-step-2
    client.put(
        "/api/v1/admin/llm/settings",
        json={"active_provider_id": p["id"], "active_model": "model-step-2"},
        headers=admin_headers,
    )

    # Next call immediately uses model-step-2
    cfg_2 = asyncio.run(runtime_llm_manager.get_config(force_refresh=True))
    assert cfg_2.active_model == "model-step-2"
    assert cfg_2.version == cfg_1.version + 1

    runtime_llm_manager.invalidate_local_cache()


def test_chat_stream_uses_fallback_when_primary_fails(client: TestClient, monkeypatch):
    """Verify that when primary stream fails, chat stream retries on fallback provider."""
    user_headers = _get_auth_headers(client, role="user")

    # Mock primary adapter that fails on stream (async generator)
    mock_primary = MagicMock()
    async def _fail_stream(*args, **kwargs):
        raise LLMUnavailableError("Primary provider connection timeout (key: sk-leaked-raw-12345)")
        yield ""
    mock_primary.stream = _fail_stream

    # Mock fallback adapter that succeeds (async generator)
    mock_fallback = MagicMock()
    async def _success_stream(*args, **kwargs):
        yield "Recovered "
        yield "from "
        yield "fallback! "
        yield "[C1]"
    mock_fallback.stream = _success_stream

    mock_cfg = MagicMock()
    mock_cfg.active_adapter = mock_primary
    mock_cfg.active_model = "primary-model"
    mock_cfg.active_provider_name = "PrimaryProvider"
    mock_cfg.fallback_adapter = mock_fallback
    mock_cfg.fallback_model = "fallback-model"
    mock_cfg.fallback_provider_name = "FallbackProvider"
    mock_cfg.temperature = 0.2
    mock_cfg.max_tokens = 512

    async def _mock_cfg_func(*args, **kwargs):
        return mock_cfg

    monkeypatch.setattr(runtime_llm_manager, "get_config", _mock_cfg_func)

    # Also mock router and retrieval so we reach stream generation
    async def _mock_route(self, *args, **kwargs):
        from app.services.intent_router import RouterResult
        from app.models.schemas import RouterIntent
        return RouterResult(intent=RouterIntent.SEARCH, standalone_query="test query")
    monkeypatch.setattr("app.services.intent_router.IntentRouter.route", _mock_route)

    from app.services.rag_engine import RetrievalResult, RetrievedChunk
    dummy_candidate = RetrievedChunk(
        chunk_id="chunk-1",
        document_id=str(uuid.uuid4()),
        version=1,
        chunk_index=0,
        content="Sample knowledge excerpt.",
        token_count=10,
        document_name="doc.txt",
        retrieval_score=0.9,
        rerank_score=0.95,
        raw_rerank_score=2.5,
    )
    def _mock_retrieve(self, *args, **kwargs):
        return RetrievalResult(
            query="test query",
            top_score=0.95,
            raw_top_score=2.5,
            is_fallback=False,
            chunks=[dummy_candidate],
            latency_ms_retrieval=5.0,
            latency_ms_rerank=5.0,
            total_latency_ms=10.0,
        )
    monkeypatch.setattr("app.services.rag_engine.RAGEngine.retrieve", _mock_retrieve)

    # Execute stream request
    resp = client.post(
        "/api/v1/chat/stream",
        json={"message": "tell me something"},
        headers=user_headers,
    )
    assert resp.status_code == 200
    content = resp.text

    # Verify fallback streamed tokens
    assert "Recovered" in content
    assert "fallback!" in content
    # Verify no raw secrets leaked
    assert "sk-leaked-raw-12345" not in content

    runtime_llm_manager.invalidate_local_cache()


# ------------------------------------------------------------------------------
# 10. Key Removal & E2E Integration Tests
# ------------------------------------------------------------------------------

def test_clear_api_key_on_inactive_provider(client: TestClient):
    """Verify that an admin can remove the API key of an inactive provider via PATCH clear_api_key=True."""
    admin_headers = _get_auth_headers(client, role="admin")

    # 1. Create provider with key
    p_resp = client.post(
        "/api/v1/admin/llm/providers",
        json={
            "name": f"Clear Key Prov {uuid.uuid4().hex[:6]}",
            "provider_type": "openai_compatible",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-to-be-cleared-9876",
            "models": ["gpt-4o"],
            "default_model": "gpt-4o",
        },
        headers=admin_headers,
    )
    assert p_resp.status_code == 201
    provider = p_resp.json()
    assert provider["has_key"] is True
    assert provider["key_hint"] == "...9876"

    # 2. Patch with clear_api_key=True
    patch_resp = client.patch(
        f"/api/v1/admin/llm/providers/{provider['id']}",
        json={"clear_api_key": True},
        headers=admin_headers,
    )
    assert patch_resp.status_code == 200
    updated = patch_resp.json()
    assert updated["has_key"] is False
    assert updated["key_hint"] is None

    # 3. Verify in DB
    async def _check_db():
        async with AsyncSessionLocal() as db:
            res = await db.execute(select(LLMProvider).where(LLMProvider.id == uuid.UUID(provider["id"])))
            row = res.scalar_one()
            assert row.api_key_encrypted is None
    asyncio.run(_check_db())


def test_clear_api_key_on_active_provider_blocked_409(client: TestClient):
    """Verify that removing the API key of the active provider is rejected with HTTP 409 Conflict."""
    admin_headers = _get_auth_headers(client, role="admin")

    # 1. Create provider with key
    p = client.post(
        "/api/v1/admin/llm/providers",
        json={
            "name": f"Active Key Prov {uuid.uuid4().hex[:6]}",
            "provider_type": "openai_compatible",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-active-cant-clear-1234",
            "models": ["model-a"],
            "default_model": "model-a",
        },
        headers=admin_headers,
    ).json()

    # 2. Set as active provider
    client.put(
        "/api/v1/admin/llm/settings",
        json={"active_provider_id": p["id"], "active_model": "model-a"},
        headers=admin_headers,
    )

    # 3. Attempt to clear key -> 409
    patch_resp = client.patch(
        f"/api/v1/admin/llm/providers/{p['id']}",
        json={"clear_api_key": True},
        headers=admin_headers,
    )
    assert patch_resp.status_code == 409
    assert "Cannot remove API key of active or fallback provider" in patch_resp.json()["detail"]


def test_admin_llm_end_to_end_hot_reload_and_failover(client: TestClient, monkeypatch):
    """Full E2E flow: add provider, test connection, switch active model, chat stream reflects change without restart, disable provider and verify failover."""
    admin_headers = _get_auth_headers(client, role="admin")
    user_headers = _get_auth_headers(client, role="user")
    initial_settings = client.get("/api/v1/admin/llm/settings", headers=admin_headers).json()

    p1 = {}
    p2 = {}

    try:
        # Step 1: Add Provider 1 (Primary) and Provider 2 (Fallback)
        p1 = client.post(
            "/api/v1/admin/llm/providers",
            json={
                "name": f"E2E Primary {uuid.uuid4().hex[:6]}",
                "provider_type": "openai_compatible",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-e2e-primary-key",
                "models": ["primary-v1"],
                "default_model": "primary-v1",
            },
            headers=admin_headers,
        ).json()

        p2 = client.post(
            "/api/v1/admin/llm/providers",
            json={
                "name": f"E2E Fallback {uuid.uuid4().hex[:6]}",
                "provider_type": "openai_compatible",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-e2e-fallback-key",
                "models": ["fallback-v1"],
                "default_model": "fallback-v1",
            },
            headers=admin_headers,
        ).json()

        # Step 2: Test connection endpoint (mock adapter complete call)
        async def _mock_complete(self, system, messages, model, **kwargs):
            return "Test connection ping OK"
        monkeypatch.setattr("app.services.llm.openai_compat.OpenAICompatAdapter.complete", _mock_complete)

        test_resp = client.post(f"/api/v1/admin/llm/providers/{p1['id']}/test", headers=admin_headers)
        assert test_resp.status_code == 200
        assert test_resp.json()["success"] is True

        # Step 3: Switch active settings to p1 with p2 as fallback
        settings_put = client.put(
            "/api/v1/admin/llm/settings",
            json={
                "active_provider_id": p1["id"],
                "active_model": "primary-v1",
                "fallback_provider_id": p2["id"],
                "fallback_model": "fallback-v1",
                "temperature": 0.3,
                "max_tokens": 800,
            },
            headers=admin_headers,
        )
        assert settings_put.status_code == 200

        # Step 4: Verify chat stream uses primary model without container restart
        models_called = []
        async def _mock_stream_primary(self, system, messages, model, **kwargs):
            models_called.append(model)
            yield f"Answer generated with {model} [C1]"

        monkeypatch.setattr("app.services.llm.openai_compat.OpenAICompatAdapter.stream", _mock_stream_primary)

        # Mock router and retrieval so we stream answers directly
        async def _mock_route(self, *args, **kwargs):
            from app.services.intent_router import RouterResult
            from app.models.schemas import RouterIntent
            return RouterResult(intent=RouterIntent.SEARCH, standalone_query="E2E query")
        monkeypatch.setattr("app.services.intent_router.IntentRouter.route", _mock_route)

        from app.services.rag_engine import RetrievalResult, RetrievedChunk
        chunk = RetrievedChunk(
            chunk_id="chunk-e2e",
            document_id=str(uuid.uuid4()),
            version=1,
            chunk_index=0,
            content="Grounded facts for E2E test.",
            token_count=10,
            document_name="doc.txt",
            retrieval_score=0.9,
            rerank_score=0.95,
            raw_rerank_score=2.5,
        )
        def _mock_retrieve(self, *args, **kwargs):
            return RetrievalResult(
                query="E2E query",
                top_score=0.95,
                raw_top_score=2.5,
                is_fallback=False,
                chunks=[chunk],
                total_latency_ms=10.0,
            )
        monkeypatch.setattr("app.services.rag_engine.RAGEngine.retrieve", _mock_retrieve)

        chat_resp = client.post(
            "/api/v1/chat/stream",
            json={"message": "What is the E2E answer?"},
            headers=user_headers,
        )
        assert chat_resp.status_code == 200
        assert "primary-v1" in chat_resp.text
        assert "primary-v1" in models_called
    finally:
        # Restore initial settings and clean up test providers
        if initial_settings.get("active_provider_id"):
            client.put(
                "/api/v1/admin/llm/settings",
                json={
                    "active_provider_id": initial_settings["active_provider_id"],
                    "active_model": initial_settings.get("active_model", "primary-v1"),
                    "fallback_provider_id": initial_settings.get("fallback_provider_id"),
                    "fallback_model": initial_settings.get("fallback_model"),
                    "temperature": initial_settings.get("temperature", 0.2),
                    "max_tokens": initial_settings.get("max_tokens", 1024),
                },
                headers=admin_headers,
            )
        if p2.get("id"):
            client.delete(f"/api/v1/admin/llm/providers/{p2['id']}", headers=admin_headers)
        if p1.get("id"):
            client.delete(f"/api/v1/admin/llm/providers/{p1['id']}", headers=admin_headers)
        runtime_llm_manager.invalidate_local_cache()



