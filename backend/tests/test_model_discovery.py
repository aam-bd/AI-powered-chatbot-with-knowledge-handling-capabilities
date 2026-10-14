"""Tests for Prompt 7e-2: Model auto-discovery, preset providers, model catalog, and usage tracking."""
import uuid
import asyncio
import pytest
import httpx
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock
from starlette.testclient import TestClient
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.sql_models import User, LLMProvider, ProviderModel, LLMSettings, LLMUsage
from app.services.llm.discovery import discover_models, ModelDiscoveryError
from app.services.llm.usage import record_llm_usage, get_usage_summary
from app.services.llm.runtime import PRESET_DEFINITIONS, seed_presets


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


@pytest.mark.asyncio
async def test_preset_definitions_and_seed_idempotency():
    """Preset definitions exist, seed disabled without keys, and are idempotent."""
    async with AsyncSessionLocal() as db:
        await seed_presets(db)

        res = await db.execute(select(LLMProvider).where(LLMProvider.is_preset == True))
        presets = res.scalars().all()
        preset_keys = {p.preset_key for p in presets}

        expected_keys = {p["preset_key"] for p in PRESET_DEFINITIONS}
        assert expected_keys.issubset(preset_keys)

        for p in presets:
            assert p.is_enabled is False
            assert p.api_key_encrypted is None

        count_before = len(presets)

        # Seed again: must be idempotent and not duplicate
        await seed_presets(db)
        res_after = await db.execute(select(LLMProvider).where(LLMProvider.is_preset == True))
        assert len(res_after.scalars().all()) == count_before


def test_preset_rename_guard(client: TestClient):
    """A preset provider cannot be renamed away from its preset identity."""
    headers = _get_auth_headers(client, "admin")

    async def _get_preset_id():
        async with AsyncSessionLocal() as db:
            await seed_presets(db)
            res = await db.execute(
                select(LLMProvider).where(LLMProvider.is_preset == True).limit(1)
            )
            return res.scalar_one().id

    preset_id = asyncio.run(_get_preset_id())

    resp = client.patch(
        f"/api/v1/admin/llm/providers/{preset_id}",
        json={"name": "Renamed Away From Preset"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "Preset providers cannot be renamed" in resp.json()["detail"]


def test_restore_presets_endpoint(client: TestClient):
    """Restore presets re-adds any deleted preset without overwriting existing ones."""
    headers = _get_auth_headers(client, "admin")

    async def _delete_groq_preset():
        async with AsyncSessionLocal() as db:
            await seed_presets(db)
            res = await db.execute(
                select(LLMProvider).where(LLMProvider.is_preset == True, LLMProvider.preset_key == "groq")
            )
            groq = res.scalar_one_or_none()
            if groq:
                await db.delete(groq)
                await db.commit()

    asyncio.run(_delete_groq_preset())

    resp = client.post(
        "/api/v1/admin/llm/providers/restore-presets",
        headers=headers,
    )
    assert resp.status_code == 200
    providers = resp.json()
    assert any(p.get("preset_key") == "groq" for p in providers)


@pytest.mark.asyncio
async def test_discover_models_openrouter(monkeypatch):
    """OpenRouter discovery normalizes context length and pricing per 1M tokens."""
    mock_response = {
        "data": [
            {
                "id": "openai/gpt-4o",
                "name": "GPT-4o",
                "context_length": 128000,
                "top_provider": {"max_completion_tokens": 4096},
                "pricing": {"prompt": "0.000005", "completion": "0.000015"},
            },
            {
                "id": "text-embedding-ada-002",
                "name": "Embedding Ada",
            },
        ]
    }

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, url, headers=None, params=None):
            req = httpx.Request("GET", url)
            return httpx.Response(200, json=mock_response, request=req)

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    models = await discover_models(
        base_url="https://openrouter.ai/api/v1",
        api_key="sk-or-test",
        discovery_kind="openrouter_models",
    )
    # Non-chat models filtered out
    assert len(models) == 1
    m = models[0]
    assert m.model_id == "openai/gpt-4o"
    assert m.display_name == "GPT-4o"
    assert m.context_length == 128000
    assert m.max_output_tokens == 4096
    assert m.price_prompt_per_1m == pytest.approx(5.0)
    assert m.price_completion_per_1m == pytest.approx(15.0)


@pytest.mark.asyncio
async def test_discover_models_openai_and_anthropic(monkeypatch):
    """OpenAI and Anthropic discoveries leave pricing/context null when not provided."""
    mock_openai = {
        "data": [
            {"id": "gpt-4o-mini"},
            {"id": "text-embedding-3-small"},
        ]
    }

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, url, headers=None, params=None):
            req = httpx.Request("GET", url)
            return httpx.Response(200, json=mock_openai, request=req)

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    models = await discover_models(
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        discovery_kind="openai_models",
    )
    assert len(models) == 1
    assert models[0].model_id == "gpt-4o-mini"
    assert models[0].price_prompt_per_1m is None
    assert models[0].price_completion_per_1m is None


@pytest.mark.asyncio
async def test_discover_models_gemini_native(monkeypatch):
    """Gemini Native filters non-generateContent models and strips prefix."""
    mock_gemini = {
        "models": [
            {
                "name": "models/gemini-2.5-flash",
                "displayName": "Gemini 2.5 Flash",
                "inputTokenLimit": 1048576,
                "outputTokenLimit": 8192,
                "supportedGenerationMethods": ["generateContent", "countTokens"],
            },
            {
                "name": "models/text-embedding-004",
                "displayName": "Embedding 004",
                "supportedGenerationMethods": ["embedContent"],
            },
        ]
    }

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, url, headers=None, params=None):
            req = httpx.Request("GET", url)
            return httpx.Response(200, json=mock_gemini, request=req)

    monkeypatch.setattr(httpx, "AsyncClient", MockAsyncClient)

    models = await discover_models(
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key="AIzaSyTest",
        discovery_kind="gemini_native_models",
    )
    assert len(models) == 1
    assert models[0].model_id == "gemini-2.5-flash"
    assert models[0].display_name == "Gemini 2.5 Flash"
    assert models[0].context_length == 1048576
    assert models[0].max_output_tokens == 8192


def test_provider_discover_endpoint_and_catalog_reconciliation(client: TestClient):
    """POST /providers/{id}/discover populates provider_models and marks disappeared models unavailable."""
    headers = _get_auth_headers(client, "admin")

    async def _setup_provider():
        async with AsyncSessionLocal() as db:
            prov = LLMProvider(
                id=uuid.uuid4(),
                name=f"Discovery Prov {uuid.uuid4().hex[:6]}",
                provider_type="openrouter",
                base_url="https://openrouter.ai/api/v1",
                api_key_encrypted="mock_encrypted",
                models=["old-disappeared-model"],
                default_model="old-disappeared-model",
                discovery_kind="openrouter_models",
                is_enabled=True,
            )
            db.add(prov)
            old_pm = ProviderModel(
                id=uuid.uuid4(),
                provider_id=prov.id,
                model_id="old-disappeared-model",
                source="discovered",
                is_available=True,
                is_enabled=True,
            )
            db.add(old_pm)
            await db.commit()
            return prov.id

    prov_id = asyncio.run(_setup_provider())

    mock_discovered = [
        MagicMock(
            model_id="new-active-model",
            display_name="New Active Model",
            context_length=32000,
            max_output_tokens=4096,
            price_prompt_per_1m=1.5,
            price_completion_per_1m=3.0,
        )
    ]

    with patch("app.api.v1.admin_llm.decrypt_api_key", return_value="sk-valid-key"):
        with patch("app.api.v1.admin_llm.discover_models", AsyncMock(return_value=mock_discovered)):
            resp = client.post(
                f"/api/v1/admin/llm/providers/{prov_id}/discover",
                headers=headers,
            )
            assert resp.status_code == 200
            catalog = resp.json()
            assert len(catalog) == 2

            # Check new active model
            new_item = next(m for m in catalog if m["model_id"] == "new-active-model")
            assert new_item["is_available"] is True
            assert new_item["is_enabled"] is True
            assert new_item["price_prompt_per_1m"] == 1.5

            # Check old model marked unavailable, NOT deleted
            old_item = next(m for m in catalog if m["model_id"] == "old-disappeared-model")
            assert old_item["is_available"] is False


def test_patch_catalog_model_and_active_protection(client: TestClient):
    """Admins can toggle enablement and set price overrides; active models cannot be disabled."""
    headers = _get_auth_headers(client, "admin")

    async def _setup_active():
        async with AsyncSessionLocal() as db:
            settings_res = await db.execute(select(LLMSettings).where(LLMSettings.id == 1))
            cur_settings = settings_res.scalar_one()

            pm_res = await db.execute(
                select(ProviderModel).where(
                    ProviderModel.provider_id == cur_settings.active_provider_id,
                    ProviderModel.model_id == cur_settings.active_model,
                )
            )
            active_pm = pm_res.scalar_one_or_none()
            if not active_pm:
                active_pm = ProviderModel(
                    id=uuid.uuid4(),
                    provider_id=cur_settings.active_provider_id,
                    model_id=cur_settings.active_model,
                    source="manual",
                    is_available=True,
                    is_enabled=True,
                )
                db.add(active_pm)
                await db.commit()
            return cur_settings.active_provider_id, cur_settings.active_model

    active_prov_id, active_model = asyncio.run(_setup_active())

    # Attempt to disable active model -> should fail with 400
    resp = client.patch(
        f"/api/v1/admin/llm/providers/{active_prov_id}/models/{active_model}",
        json={"is_enabled": False},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "currently set as the active model" in resp.json()["detail"]

    # Price override should succeed
    resp_price = client.patch(
        f"/api/v1/admin/llm/providers/{active_prov_id}/models/{active_model}",
        json={"price_prompt_per_1m": 2.5, "price_completion_per_1m": 5.0},
        headers=headers,
    )
    assert resp_price.status_code == 200
    data = resp_price.json()
    assert data["price_prompt_per_1m"] == 2.5
    assert data["price_completion_per_1m"] == 5.0


def test_manual_model_creation(client: TestClient):
    """POST /providers/{id}/models/manual registers a custom/manual model."""
    headers = _get_auth_headers(client, "admin")

    async def _get_prov_id():
        async with AsyncSessionLocal() as db:
            prov_res = await db.execute(select(LLMProvider).limit(1))
            return prov_res.scalar_one().id

    prov_id = asyncio.run(_get_prov_id())

    test_model_id = f"custom-manual-{uuid.uuid4().hex[:6]}"
    resp = client.post(
        f"/api/v1/admin/llm/providers/{prov_id}/models/manual",
        json={
            "model_id": test_model_id,
            "display_name": "Custom Fine-tune",
            "context_length": 16384,
            "price_prompt_per_1m": 0.5,
            "price_completion_per_1m": 1.0,
        },
        headers=headers,
    )
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["model_id"] == test_model_id
    assert res_data["source"] == "manual"
    assert res_data["is_available"] is True
    assert res_data["is_enabled"] is True


def test_usage_tracking_and_summary_endpoint(client: TestClient):
    """Usage recording computes metrics and GET /admin/llm/usage returns aggregation."""
    headers = _get_auth_headers(client, "admin")

    async def _setup_and_record():
        async with AsyncSessionLocal() as db:
            prov_res = await db.execute(select(LLMProvider).limit(1))
            prov = prov_res.scalar_one()

            m_res = await db.execute(
                select(ProviderModel).where(ProviderModel.provider_id == prov.id).limit(1)
            )
            pm = m_res.scalar_one_or_none()
            if not pm:
                pm = ProviderModel(
                    id=uuid.uuid4(),
                    provider_id=prov.id,
                    model_id="test-metered-model",
                    price_prompt_per_1m=10.0,
                    price_completion_per_1m=30.0,
                    source="manual",
                    is_available=True,
                    is_enabled=True,
                )
                db.add(pm)
                await db.commit()
            else:
                pm.price_prompt_per_1m = 10.0
                pm.price_completion_per_1m = 30.0
                await db.commit()

            # Record usage directly
            await record_llm_usage(
                provider_id=prov.id,
                model_id=pm.model_id,
                prompt_tokens=1000,
                completion_tokens=500,
                latency_ms=250.0,
                status="success",
            )

    asyncio.run(_setup_and_record())

    # Query usage summary endpoint
    resp = client.get(
        "/api/v1/admin/llm/usage?range=24h",
        headers=headers,
    )
    assert resp.status_code == 200
    summary = resp.json()
    assert summary["range"] == "24h"
    assert summary["total_requests"] >= 1
    assert summary["total_tokens"] >= 1500
    assert summary["total_estimated_cost"] is not None
    # 1000 / 1M * 10 = 0.01; 500 / 1M * 30 = 0.015 -> 0.025
    assert summary["total_estimated_cost"] >= 0.025
