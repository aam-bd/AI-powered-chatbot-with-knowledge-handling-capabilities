"""Admin endpoints for dynamic LLM provider and settings management.

Complies strictly with Prompt 7e and Architecture §6, §8, §9, §11:
- Admin only (non-admins receive HTTP 403 FORBIDDEN).
- API keys are encrypted at rest with Fernet and never echoed in API responses or logs.
- Base URLs are validated with SSRF protections.
- Hot reload version incrementing and Redis synchronization.
- Connection test endpoint is rate-limited with sanitized error reporting.
- Complete audit logging with secret redaction.
"""
import uuid
import asyncio
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.logger import logger
from app.core.rate_limit import RateLimiter
from app.core.security import require_admin
from app.core.crypto import encrypt_api_key, decrypt_api_key, get_key_hint
from app.db.session import get_db
from app.db.redis import get_redis_client
from app.models.sql_models import User, LLMProvider, LLMSettings
from app.models.schemas import (
    LLMProviderCreate,
    LLMProviderUpdate,
    LLMProviderResponse,
    LLMProviderTestResponse,
    LLMModelsResponse,
    LLMSettingsResponse,
    LLMSettingsUpdate,
)
from app.services.llm.base import validate_base_url, LLMError
from app.services.llm.openai_compat import OpenAICompatAdapter
from app.services.llm.anthropic import AnthropicAdapter
from app.services.llm.runtime import REDIS_VERSION_KEY, runtime_llm_manager

router = APIRouter(prefix="/admin/llm", tags=["admin-llm"])


def _mask_provider_response(p: LLMProvider) -> LLMProviderResponse:
    """Format provider for admin API response without ever revealing raw API key."""
    has_key = bool(p.api_key_encrypted and p.api_key_encrypted.strip())
    hint = get_key_hint(p.api_key_encrypted, is_encrypted=True) if has_key else None
    return LLMProviderResponse(
        id=p.id,
        name=p.name,
        provider_type=p.provider_type,
        base_url=p.base_url,
        has_key=has_key,
        key_hint=hint,
        models=p.models or [],
        default_model=p.default_model,
        is_enabled=p.is_enabled,
        created_at=p.created_at,
        updated_at=p.updated_at,
        last_test_status=p.last_test_status,
        last_test_at=p.last_test_at,
    )


# ------------------------------------------------------------------------------
# 1. Provider CRUD Endpoints
# ------------------------------------------------------------------------------

@router.get("/providers", response_model=List[LLMProviderResponse])
async def list_providers(
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> List[LLMProviderResponse]:
    """List all registered LLM providers. Keys are masked to safe hints."""
    result = await db.execute(select(LLMProvider).order_by(LLMProvider.created_at.asc()))
    providers = result.scalars().all()
    return [_mask_provider_response(p) for p in providers]


@router.post("/providers", response_model=LLMProviderResponse, status_code=status.HTTP_201_CREATED)
async def create_provider(
    payload: LLMProviderCreate,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> LLMProviderResponse:
    """Add a new LLM provider with SSRF validation and encrypted API key."""
    # Check duplicate name
    dup_res = await db.execute(select(LLMProvider).where(LLMProvider.name == payload.name.strip()))
    if dup_res.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An LLM provider named '{payload.name}' already exists.",
        )

    # SSRF Base URL Validation
    try:
        validated_url = validate_base_url(
            payload.base_url,
            allow_private=settings.ALLOW_PRIVATE_LLM_URLS,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    # Encrypt API Key
    encrypted_key = encrypt_api_key(payload.api_key) if payload.api_key else None

    provider = LLMProvider(
        id=uuid.uuid4(),
        name=payload.name.strip(),
        provider_type=payload.provider_type.strip(),
        base_url=validated_url,
        api_key_encrypted=encrypted_key,
        models=payload.models,
        default_model=payload.default_model.strip(),
        is_enabled=payload.is_enabled,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)

    logger.info(
        f"ADMIN_AUDIT: user_id={current_admin.id} action=CREATE_LLM_PROVIDER "
        f"provider_id={provider.id} name={provider.name} type={provider.provider_type}"
    )

    return _mask_provider_response(provider)


@router.patch("/providers/{provider_id}", response_model=LLMProviderResponse)
async def update_provider(
    provider_id: uuid.UUID,
    payload: LLMProviderUpdate,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> LLMProviderResponse:
    """Update provider details. Replaces API key only if a new non-empty key is provided."""
    res = await db.execute(select(LLMProvider).where(LLMProvider.id == provider_id))
    provider = res.scalar_one_or_none()
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LLM provider '{provider_id}' not found.",
        )

    # Check name uniqueness if changed
    if payload.name and payload.name.strip() != provider.name:
        dup_res = await db.execute(
            select(LLMProvider).where(LLMProvider.name == payload.name.strip(), LLMProvider.id != provider_id)
        )
        if dup_res.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"An LLM provider named '{payload.name}' already exists.",
            )
        provider.name = payload.name.strip()

    # Base URL with SSRF validation
    if payload.base_url:
        try:
            provider.base_url = validate_base_url(
                payload.base_url,
                allow_private=settings.ALLOW_PRIVATE_LLM_URLS,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )

    # Models & default model
    if payload.models is not None:
        provider.models = payload.models
    if payload.default_model is not None:
        if payload.default_model not in provider.models:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"default_model '{payload.default_model}' must be in provider models.",
            )
        provider.default_model = payload.default_model.strip()

    # Enabled toggle
    if payload.is_enabled is not None:
        if not payload.is_enabled:
            # Cannot disable if currently configured as active provider
            settings_res = await db.execute(select(LLMSettings).where(LLMSettings.id == 1))
            cur_settings = settings_res.scalar_one_or_none()
            if cur_settings and cur_settings.active_provider_id == provider.id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot disable the provider that is currently active in LLM settings.",
                )
        provider.is_enabled = payload.is_enabled

    # API Key: explicit clear or update
    key_cleared = False
    key_updated = False
    if payload.clear_api_key:
        settings_res = await db.execute(select(LLMSettings).where(LLMSettings.id == 1))
        cur_settings = settings_res.scalar_one_or_none()
        if cur_settings and (cur_settings.active_provider_id == provider.id or cur_settings.fallback_provider_id == provider.id):
            if provider.provider_type.lower() not in ("ollama", "local", "custom"):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Cannot remove API key of active or fallback provider. Reassign active/fallback provider or provide a new key first.",
                )
        provider.api_key_encrypted = None
        key_cleared = True
    elif payload.api_key is not None and payload.api_key.strip():
        provider.api_key_encrypted = encrypt_api_key(payload.api_key.strip())
        key_updated = True

    provider.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(provider)

    # Invalidate runtime cache and bump version if active provider was updated
    settings_res = await db.execute(select(LLMSettings).where(LLMSettings.id == 1))
    cur_settings = settings_res.scalar_one_or_none()
    if cur_settings and cur_settings.active_provider_id == provider.id:
        cur_settings.version += 1
        await db.commit()
        try:
            redis_client = get_redis_client()
            await redis_client.set(REDIS_VERSION_KEY, str(cur_settings.version))
        except Exception:
            pass
        runtime_llm_manager.invalidate_local_cache()

    logger.info(
        f"ADMIN_AUDIT: user_id={current_admin.id} action=UPDATE_LLM_PROVIDER "
        f"provider_id={provider.id} is_enabled={provider.is_enabled} "
        f"key_updated={key_updated} key_cleared={key_cleared}"
    )

    return _mask_provider_response(provider)


@router.delete("/providers/{provider_id}")
async def delete_provider(
    provider_id: uuid.UUID,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Delete an LLM provider. Refuses if provider is configured as active or fallback."""
    res = await db.execute(select(LLMProvider).where(LLMProvider.id == provider_id))
    provider = res.scalar_one_or_none()
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LLM provider '{provider_id}' not found.",
        )

    # In-use check
    settings_res = await db.execute(select(LLMSettings).where(LLMSettings.id == 1))
    cur_settings = settings_res.scalar_one_or_none()
    if cur_settings:
        if cur_settings.active_provider_id == provider_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot delete provider that is currently active in LLM settings.",
            )
        if cur_settings.fallback_provider_id == provider_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot delete provider that is currently configured as fallback in LLM settings.",
            )

    await db.delete(provider)
    await db.commit()

    logger.info(
        f"ADMIN_AUDIT: user_id={current_admin.id} action=DELETE_LLM_PROVIDER provider_id={provider_id}"
    )

    return {"detail": "Provider deleted successfully", "code": "PROVIDER_DELETED"}


# ------------------------------------------------------------------------------
# 2. Connection Test Endpoint (Rate-Limited)
# ------------------------------------------------------------------------------

@router.post(
    "/providers/{provider_id}/test",
    response_model=LLMProviderTestResponse,
    dependencies=[Depends(RateLimiter(times=5, seconds=60, route_name="/admin/llm/test"))],
)
async def test_provider_connection(
    provider_id: uuid.UUID,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> LLMProviderTestResponse:
    """Test connection with provider via short minimal completion. Secrets are never echoed."""
    res = await db.execute(select(LLMProvider).where(LLMProvider.id == provider_id))
    provider = res.scalar_one_or_none()
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LLM provider '{provider_id}' not found.",
        )

    decrypted_key = decrypt_api_key(provider.api_key_encrypted) if provider.api_key_encrypted else ""
    norm_type = provider.provider_type.lower().strip()
    test_model = provider.default_model or (provider.models[0] if provider.models else "default")

    if norm_type == "anthropic":
        adapter = AnthropicAdapter(
            api_key=decrypted_key,
            base_url=provider.base_url,
            timeout=8.0,
            max_retries=1,
        )
    else:
        adapter = OpenAICompatAdapter(
            api_key=decrypted_key,
            base_url=provider.base_url,
            timeout=8.0,
            max_retries=1,
        )

    success = False
    sanitized_error = None
    try:
        # Minimal ping completion
        await asyncio.wait_for(
            adapter.complete(
                system="Respond with OK.",
                messages=[{"role": "user", "content": "ping"}],
                model=test_model,
                max_tokens=3,
                temperature=0.0,
            ),
            timeout=8.0,
        )
        success = True
        status_str = "success"
        message = f"Connection to '{provider.name}' succeeded."
    except Exception as exc:
        status_str = "failed"
        message = f"Connection to '{provider.name}' failed."
        # Sanitize error to remove API key or internal secrets
        err_msg = str(exc)
        if decrypted_key and len(decrypted_key) > 4:
            err_msg = err_msg.replace(decrypted_key, "[REDACTED]")
        sanitized_error = f"{type(exc).__name__}: {err_msg[:200]}"

    # Update provider status
    provider.last_test_status = status_str
    provider.last_test_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info(
        f"ADMIN_AUDIT: user_id={current_admin.id} action=TEST_LLM_PROVIDER "
        f"provider_id={provider.id} status={status_str}"
    )

    return LLMProviderTestResponse(
        success=success,
        status=status_str,
        message=message,
        sanitized_error=sanitized_error,
    )


# ------------------------------------------------------------------------------
# 3. Dynamic Models Listing
# ------------------------------------------------------------------------------

@router.get("/models", response_model=LLMModelsResponse)
async def get_provider_models(
    provider_id: uuid.UUID = Query(..., description="ID of the provider"),
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> LLMModelsResponse:
    """List available models for provider (dynamic fetch where supported, otherwise stored list)."""
    res = await db.execute(select(LLMProvider).where(LLMProvider.id == provider_id))
    provider = res.scalar_one_or_none()
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"LLM provider '{provider_id}' not found.",
        )

    # Stored fallback models
    stored_models = list(provider.models or [])

    # Dynamic model fetch attempt for OpenAI-compatible providers
    if provider.provider_type in ("openai_compatible", "openai", "openrouter", "ollama"):
        try:
            import httpx
            decrypted_key = decrypt_api_key(provider.api_key_encrypted) if provider.api_key_encrypted else ""
            headers = {"Authorization": f"Bearer {decrypted_key}"} if decrypted_key else {}
            models_url = f"{provider.base_url.rstrip('/')}/models"
            
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(models_url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    model_items = data.get("data", [])
                    extracted_models = [m["id"] for m in model_items if "id" in m]
                    if extracted_models:
                        return LLMModelsResponse(
                            provider_id=provider.id,
                            models=extracted_models[:50],
                            source="provider",
                        )
        except Exception:
            pass

    return LLMModelsResponse(
        provider_id=provider.id,
        models=stored_models,
        source="stored",
    )


# ------------------------------------------------------------------------------
# 4. LLM Runtime Settings Endpoints
# ------------------------------------------------------------------------------

@router.get("/settings", response_model=LLMSettingsResponse)
async def get_llm_settings(
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> LLMSettingsResponse:
    """Get active and fallback LLM configuration settings."""
    query = (
        select(LLMSettings)
        .options(
            selectinload(LLMSettings.active_provider),
            selectinload(LLMSettings.fallback_provider),
        )
        .where(LLMSettings.id == 1)
    )
    res = await db.execute(query)
    s = res.scalar_one_or_none()
    if not s:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="LLM settings row not initialized in database.",
        )

    return LLMSettingsResponse(
        active_provider_id=s.active_provider_id,
        active_model=s.active_model,
        fallback_provider_id=s.fallback_provider_id,
        fallback_model=s.fallback_model,
        temperature=s.temperature,
        max_tokens=s.max_tokens,
        version=s.version,
        active_provider_name=s.active_provider.name if s.active_provider else None,
        active_provider_type=s.active_provider.provider_type if s.active_provider else None,
        fallback_provider_name=s.fallback_provider.name if s.fallback_provider else None,
        fallback_provider_type=s.fallback_provider.provider_type if s.fallback_provider else None,
    )


@router.put("/settings", response_model=LLMSettingsResponse)
async def update_llm_settings(
    payload: LLMSettingsUpdate,
    current_admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> LLMSettingsResponse:
    """Update active/fallback LLM providers, model selection, and generation parameters."""
    # 1. Validate active provider
    act_res = await db.execute(select(LLMProvider).where(LLMProvider.id == payload.active_provider_id))
    active_prov = act_res.scalar_one_or_none()
    if not active_prov:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Active provider '{payload.active_provider_id}' does not exist.",
        )
    if not active_prov.is_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Active provider '{active_prov.name}' is disabled and cannot be activated.",
        )
    if payload.active_model not in active_prov.models:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Active model '{payload.active_model}' does not belong to provider '{active_prov.name}' models: {active_prov.models}",
        )

    # 2. Validate fallback provider if specified
    fallback_prov = None
    if payload.fallback_provider_id:
        fb_res = await db.execute(select(LLMProvider).where(LLMProvider.id == payload.fallback_provider_id))
        fallback_prov = fb_res.scalar_one_or_none()
        if not fallback_prov:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Fallback provider '{payload.fallback_provider_id}' does not exist.",
            )
        if not fallback_prov.is_enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Fallback provider '{fallback_prov.name}' is disabled and cannot be set as fallback.",
            )
        if not payload.fallback_model:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="fallback_model must be specified when fallback_provider_id is provided.",
            )
        if payload.fallback_model not in fallback_prov.models:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Fallback model '{payload.fallback_model}' does not belong to provider '{fallback_prov.name}' models.",
            )
    else:
        if payload.fallback_model:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="fallback_provider_id must be specified when fallback_model is provided.",
            )

    # 3. Load or create singleton settings row
    settings_res = await db.execute(
        select(LLMSettings)
        .options(
            selectinload(LLMSettings.active_provider),
            selectinload(LLMSettings.fallback_provider),
        )
        .where(LLMSettings.id == 1)
    )
    cur_settings = settings_res.scalar_one_or_none()
    if not cur_settings:
        cur_settings = LLMSettings(id=1, version=1)
        db.add(cur_settings)

    cur_settings.active_provider_id = payload.active_provider_id
    cur_settings.active_model = payload.active_model
    cur_settings.fallback_provider_id = payload.fallback_provider_id
    cur_settings.fallback_model = payload.fallback_model
    cur_settings.temperature = payload.temperature
    cur_settings.max_tokens = payload.max_tokens
    cur_settings.version += 1

    await db.commit()
    await db.refresh(cur_settings)

    # 4. Synchronize Redis version & invalidate local runtime cache
    try:
        redis_client = get_redis_client()
        await redis_client.set(REDIS_VERSION_KEY, str(cur_settings.version))
    except Exception as redis_exc:
        logger.warning(f"Failed to publish settings version to Redis: {redis_exc}")

    runtime_llm_manager.invalidate_local_cache()

    logger.info(
        f"ADMIN_AUDIT: user_id={current_admin.id} action=UPDATE_LLM_SETTINGS "
        f"active_provider_id={cur_settings.active_provider_id} active_model={cur_settings.active_model} "
        f"fallback_provider_id={cur_settings.fallback_provider_id} version={cur_settings.version}"
    )

    return LLMSettingsResponse(
        active_provider_id=cur_settings.active_provider_id,
        active_model=cur_settings.active_model,
        fallback_provider_id=cur_settings.fallback_provider_id,
        fallback_model=cur_settings.fallback_model,
        temperature=cur_settings.temperature,
        max_tokens=cur_settings.max_tokens,
        version=cur_settings.version,
        active_provider_name=active_prov.name,
        active_provider_type=active_prov.provider_type,
        fallback_provider_name=fallback_prov.name if fallback_prov else None,
        fallback_provider_type=fallback_prov.provider_type if fallback_prov else None,
    )
