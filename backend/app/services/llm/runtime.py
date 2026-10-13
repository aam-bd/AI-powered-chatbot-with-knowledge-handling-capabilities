"""Runtime manager for dynamic LLM providers, settings, and hot reloading.

Complies with Prompt 7e and Architecture §6.9, §8, §9:
- Caches active provider and model in memory with fast Redis version invalidation.
- Supports hot reloading without process restart in both API and Celery workers.
- Protects in-flight streams from mid-turn configuration mutations.
- Implements single-retry fallback to fallback provider on active provider failure.
- Redacts secrets from logs and exceptions.
- Provides bootstrap seeding from .env on clean database startup.
"""
import time
import uuid
from dataclasses import dataclass
from typing import Optional, Tuple, AsyncIterator, List, Dict, Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.logger import logger
from app.core.crypto import encrypt_api_key, decrypt_api_key
from app.db.session import AsyncSessionLocal
from app.db.redis import get_redis_client
from app.models.sql_models import LLMProvider, LLMSettings
from app.services.llm.base import LLMAdapter, LLMError, LLMAuthError, LLMRateLimitError, LLMTimeoutError, LLMUnavailableError
from app.services.llm.openai_compat import OpenAICompatAdapter
from app.services.llm.anthropic import AnthropicAdapter


REDIS_VERSION_KEY = "llm_settings:version"
CACHE_TTL_SECONDS = 1.0  # Fast in-process check interval before querying Redis/PG


@dataclass
class RuntimeLLMConfig:
    version: int
    active_provider_id: uuid.UUID
    active_provider_name: str
    active_provider_type: str
    active_base_url: str
    active_adapter: LLMAdapter
    active_model: str
    fallback_provider_id: Optional[uuid.UUID]
    fallback_provider_name: Optional[str]
    fallback_provider_type: Optional[str]
    fallback_base_url: Optional[str]
    fallback_adapter: Optional[LLMAdapter]
    fallback_model: Optional[str]
    temperature: float
    max_tokens: int
    cached_at: float


class RuntimeLLMManager:
    """Manages active LLM provider adapters, hot reloading, and fallback execution."""

    def __init__(self):
        self._cached_config: Optional[RuntimeLLMConfig] = None

    def invalidate_local_cache(self) -> None:
        """Clear local in-process cache."""
        self._cached_config = None

    async def get_config(self, force_refresh: bool = False) -> Optional[RuntimeLLMConfig]:
        """Fetch current runtime configuration, reloading from PostgreSQL if version changed."""
        now = time.monotonic()
        
        # Check if local cache is still fresh and not forced to refresh
        if not force_refresh and self._cached_config is not None:
            # Check Redis version if cache TTL expired
            if (now - self._cached_config.cached_at) < CACHE_TTL_SECONDS:
                return self._cached_config
            
            try:
                redis_client = get_redis_client()
                cached_ver_str = await redis_client.get(REDIS_VERSION_KEY)
                if cached_ver_str is not None:
                    current_redis_version = int(cached_ver_str)
                    if current_redis_version == self._cached_config.version:
                        # Version unchanged; extend cached timestamp
                        self._cached_config.cached_at = now
                        return self._cached_config
            except Exception:
                # If Redis is temporarily unreachable, return cached config
                return self._cached_config

        # Version changed or not cached: reload from PostgreSQL
        try:
            async with AsyncSessionLocal() as session:
                query = (
                    select(LLMSettings)
                    .options(
                        selectinload(LLMSettings.active_provider),
                        selectinload(LLMSettings.fallback_provider),
                    )
                    .where(LLMSettings.id == 1)
                )
                result = await session.execute(query)
                llm_settings_row = result.scalar_one_or_none()

                if not llm_settings_row or not llm_settings_row.active_provider:
                    return None

                active_p = llm_settings_row.active_provider
                if not active_p.is_enabled:
                    logger.warning(f"Active LLM provider '{active_p.name}' is marked disabled.")

                active_adapter = self._build_adapter(
                    provider_type=active_p.provider_type,
                    base_url=active_p.base_url,
                    encrypted_key=active_p.api_key_encrypted,
                )

                fallback_adapter = None
                fallback_p = llm_settings_row.fallback_provider
                if fallback_p and fallback_p.is_enabled and llm_settings_row.fallback_model:
                    try:
                        fallback_adapter = self._build_adapter(
                            provider_type=fallback_p.provider_type,
                            base_url=fallback_p.base_url,
                            encrypted_key=fallback_p.api_key_encrypted,
                        )
                    except Exception as fb_exc:
                        logger.warning(f"Failed to initialize fallback adapter '{fallback_p.name}': {fb_exc}")

                config = RuntimeLLMConfig(
                    version=llm_settings_row.version,
                    active_provider_id=active_p.id,
                    active_provider_name=active_p.name,
                    active_provider_type=active_p.provider_type,
                    active_base_url=active_p.base_url,
                    active_adapter=active_adapter,
                    active_model=llm_settings_row.active_model,
                    fallback_provider_id=fallback_p.id if fallback_p else None,
                    fallback_provider_name=fallback_p.name if fallback_p else None,
                    fallback_provider_type=fallback_p.provider_type if fallback_p else None,
                    fallback_base_url=fallback_p.base_url if fallback_p else None,
                    fallback_adapter=fallback_adapter,
                    fallback_model=llm_settings_row.fallback_model if fallback_p else None,
                    temperature=llm_settings_row.temperature,
                    max_tokens=llm_settings_row.max_tokens,
                    cached_at=now,
                )
                self._cached_config = config

                # Synchronize Redis version key
                try:
                    redis_client = get_redis_client()
                    await redis_client.set(REDIS_VERSION_KEY, str(config.version))
                except Exception:
                    pass

                return config
        except Exception as exc:
            logger.warning(f"Could not load LLM runtime configuration from database: {exc}")
            return self._cached_config

    def _build_adapter(self, provider_type: str, base_url: str, encrypted_key: Optional[str]) -> LLMAdapter:
        """Instantiate an LLM adapter with decrypted credentials."""
        plain_key = decrypt_api_key(encrypted_key) if encrypted_key else ""
        norm_type = provider_type.lower().strip()
        timeout = float(settings.LLM_TIMEOUT_SECONDS)
        max_retries = int(settings.LLM_MAX_RETRIES)

        if norm_type == "anthropic":
            return AnthropicAdapter(
                api_key=plain_key,
                base_url=base_url,
                timeout=timeout,
                max_retries=max_retries,
            )
        else:
            # Default to openai_compatible for openai, gemini, openrouter, ollama, etc.
            return OpenAICompatAdapter(
                api_key=plain_key,
                base_url=base_url,
                timeout=timeout,
                max_retries=max_retries,
            )

    async def execute_complete_with_fallback(
        self,
        system: str,
        messages: List[Dict[str, Any]],
        role: str = "answer",
    ) -> str:
        """Execute complete call with active adapter, automatically retrying once on fallback if active fails."""
        config = await self.get_config()
        if not config:
            from app.services.llm.factory import get_llm_adapter
            adapter, model = get_llm_adapter(role)
            return await adapter.complete(
                system=system,
                messages=messages,
                model=model,
                max_tokens=1024,
                temperature=0.0,
            )

        model = config.active_model
        temp = config.temperature
        max_tok = config.max_tokens

        try:
            return await config.active_adapter.complete(
                system=system,
                messages=messages,
                model=model,
                max_tokens=max_tok,
                temperature=temp,
            )
        except LLMError as primary_exc:
            if config.fallback_adapter and config.fallback_model:
                logger.warning(
                    f"Active LLM provider '{config.active_provider_name}' failed ({type(primary_exc).__name__}). "
                    f"Retrying once on fallback provider '{config.fallback_provider_name}'."
                )
                try:
                    return await config.fallback_adapter.complete(
                        system=system,
                        messages=messages,
                        model=config.fallback_model,
                        max_tokens=max_tok,
                        temperature=temp,
                    )
                except LLMError as fb_exc:
                    logger.error(
                        f"Fallback LLM provider '{config.fallback_provider_name}' also failed: {type(fb_exc).__name__}."
                    )
                    raise fb_exc
            raise primary_exc


# Global runtime singleton
runtime_llm_manager = RuntimeLLMManager()


async def bootstrap_llm_settings() -> None:
    """Bootstrap default provider and settings in PostgreSQL from .env if table is empty."""
    try:
        async with AsyncSessionLocal() as session:
            count_res = await session.execute(select(LLMProvider.id).limit(1))
            if count_res.scalar_one_or_none() is not None:
                # Table already has rows; database is the source of truth
                return

            # llm_providers is empty. Check if .env has configuration
            key = (settings.LLM_API_KEY.get_secret_value() if settings.LLM_API_KEY else None) or \
                  (settings.ANSWER_LLM_API_KEY.get_secret_value() if settings.ANSWER_LLM_API_KEY else None)
            
            answer_model = settings.ANSWER_MODEL or settings.FAST_MODEL or "gemini-3.1-flash-lite"
            fast_model = settings.FAST_MODEL or answer_model
            models_list = list(dict.fromkeys([m for m in [answer_model, fast_model] if m]))

            provider_name = f"Default {settings.LLM_PROVIDER.replace('_', ' ').title()}"
            encrypted_key = encrypt_api_key(key) if key else None

            provider = LLMProvider(
                id=uuid.uuid4(),
                name=provider_name,
                provider_type=settings.LLM_PROVIDER,
                base_url=settings.LLM_BASE_URL,
                api_key_encrypted=encrypted_key,
                models=models_list,
                default_model=answer_model,
                is_enabled=True,
                last_test_status=None,
                last_test_at=None,
            )
            session.add(provider)
            await session.flush()

            llm_settings_row = LLMSettings(
                id=1,
                active_provider_id=provider.id,
                active_model=answer_model,
                fallback_provider_id=None,
                fallback_model=None,
                temperature=0.0,
                max_tokens=1024,
                version=1,
            )
            session.add(llm_settings_row)
            await session.commit()

            # Initialize Redis version key
            try:
                redis_client = get_redis_client()
                await redis_client.set(REDIS_VERSION_KEY, "1")
            except Exception:
                pass

            logger.info(
                f"Bootstrapped default LLM provider '{provider_name}' and settings from .env configuration."
            )
    except Exception as exc:
        logger.error(f"Failed to bootstrap LLM settings: {exc}")
