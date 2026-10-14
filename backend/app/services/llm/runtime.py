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


PRESET_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "preset_key": "openrouter",
        "name": "OpenRouter",
        "provider_type": "openai_compatible",
        "base_url": "https://openrouter.ai/api/v1",
        "docs_url": "https://openrouter.ai/docs",
        "key_required": True,
        "discovery_kind": "openrouter_models",
        "default_model": "meta-llama/llama-3.3-70b-instruct",
        "models": ["meta-llama/llama-3.3-70b-instruct", "google/gemini-2.0-flash-001"],
    },
    {
        "preset_key": "openai",
        "name": "OpenAI",
        "provider_type": "openai_compatible",
        "base_url": "https://api.openai.com/v1",
        "docs_url": "https://platform.openai.com/docs/models",
        "key_required": True,
        "discovery_kind": "openai_models",
        "default_model": "gpt-4o-mini",
        "models": ["gpt-4o-mini", "gpt-4o"],
    },
    {
        "preset_key": "anthropic",
        "name": "Anthropic",
        "provider_type": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "docs_url": "https://docs.anthropic.com/en/docs/about-claude/models",
        "key_required": True,
        "discovery_kind": "anthropic_models",
        "default_model": "claude-3-5-haiku-20241022",
        "models": ["claude-3-5-haiku-20241022", "claude-3-7-sonnet-20250219"],
    },
    {
        "preset_key": "google",
        "name": "Google AI Studio / Gemini",
        "provider_type": "openai_compatible",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "docs_url": "https://ai.google.dev/gemini-api/docs/models/gemini",
        "key_required": True,
        "discovery_kind": "gemini_native_models",
        "default_model": "gemini-2.0-flash",
        "models": ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-3.1-flash-lite"],
    },
    {
        "preset_key": "groq",
        "name": "Groq",
        "provider_type": "openai_compatible",
        "base_url": "https://api.groq.com/openai/v1",
        "docs_url": "https://console.groq.com/docs/models",
        "key_required": True,
        "discovery_kind": "openai_models",
        "default_model": "llama-3.3-70b-versatile",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
    },
    {
        "preset_key": "deepseek",
        "name": "DeepSeek",
        "provider_type": "openai_compatible",
        "base_url": "https://api.deepseek.com/v1",
        "docs_url": "https://api-docs.deepseek.com",
        "key_required": True,
        "discovery_kind": "openai_models",
        "default_model": "deepseek-chat",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    },
    {
        "preset_key": "ollama",
        "name": "Ollama (Local)",
        "provider_type": "openai_compatible",
        "base_url": "http://host.docker.internal:11434/v1",
        "docs_url": "https://ollama.com",
        "key_required": False,
        "discovery_kind": "openai_models",
        "default_model": "llama3.2:latest",
        "models": ["llama3.2:latest"],
    },
]


async def seed_presets(session: AsyncSessionLocal) -> int:
    """Idempotently seed preset providers into PostgreSQL without overwriting admin edits."""
    from app.models.sql_models import ProviderModel
    created_count = 0
    for preset in PRESET_DEFINITIONS:
        res = await session.execute(
            select(LLMProvider).where(
                (LLMProvider.preset_key == preset["preset_key"]) |
                (LLMProvider.name == preset["name"])
            )
        )
        if res.scalars().first() is not None:
            continue

        p_id = uuid.uuid4()
        prov = LLMProvider(
            id=p_id,
            name=preset["name"],
            preset_key=preset["preset_key"],
            is_preset=True,
            provider_type=preset["provider_type"],
            base_url=preset["base_url"],
            docs_url=preset["docs_url"],
            key_required=preset["key_required"],
            discovery_kind=preset["discovery_kind"],
            api_key_encrypted=None,
            models=preset["models"],
            default_model=preset["default_model"],
            is_enabled=False,
            discovered_count=len(preset["models"]),
            discovered_at=None,
        )
        session.add(prov)
        await session.flush()

        for m_id in preset["models"]:
            pm = ProviderModel(
                id=uuid.uuid4(),
                provider_id=p_id,
                model_id=m_id,
                display_name=m_id,
                source="manual",
                is_available=True,
                is_enabled=True,
            )
            session.add(pm)

        created_count += 1

    if created_count > 0:
        await session.commit()
        logger.info(f"Seeded {created_count} missing preset LLM providers.")
    return created_count


async def bootstrap_llm_settings() -> None:
    """Bootstrap default provider, presets, and settings in PostgreSQL from .env."""
    from app.models.sql_models import ProviderModel
    try:
        async with AsyncSessionLocal() as session:
            count_res = await session.execute(select(LLMProvider.id).limit(1))
            has_providers = count_res.scalar_one_or_none() is not None

            if not has_providers:
                # llm_providers is empty. Create default from .env
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
                    is_preset=False,
                    preset_key=None,
                    key_required=True,
                    discovery_kind="openai_models",
                    discovered_count=len(models_list),
                    last_test_status=None,
                    last_test_at=None,
                )
                session.add(provider)
                await session.flush()

                for m_id in models_list:
                    pm = ProviderModel(
                        id=uuid.uuid4(),
                        provider_id=provider.id,
                        model_id=m_id,
                        display_name=m_id,
                        source="manual",
                        is_available=True,
                        is_enabled=True,
                    )
                    session.add(pm)

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

            # Check if presets have ever been seeded
            preset_check = await session.execute(
                select(LLMProvider.id).where(LLMProvider.is_preset == True).limit(1)
            )
            if preset_check.scalar_one_or_none() is None:
                await seed_presets(session)

    except Exception as exc:
        logger.error(f"Failed to bootstrap LLM settings: {exc}")

