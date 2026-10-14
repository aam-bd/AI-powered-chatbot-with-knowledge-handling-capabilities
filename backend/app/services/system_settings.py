"""Runtime system settings manager and hot-reload service.

Complies with Prompt 7e-3:
- Caches system settings in memory with sub-second Redis version invalidation.
- Supports runtime-editable settings: reranker_threshold, retrieval_top_k, rerank_top_n,
  history_messages, rate_limit_per_minute, rate_limit_login_per_minute, sse_keepalive_interval,
  and max_upload_size_bytes.
- Enforces strict validation bounds and invariants (rerank_top_n <= retrieval_top_k).
- Issues prominent grounding warning if reranker_threshold is lowered below 0.50.
- Maintains comprehensive audit log entries for all updates and resets.
- Propagates version updates to Celery workers and API processes via Redis Pub/Sub.
"""
import time
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy import select, update
from app.core.config import settings as env_settings
from app.core.logger import logger
from app.db.session import AsyncSessionLocal
from app.db.redis import get_redis_client
from app.models.sql_models import SystemSettings, AuditLog
from app.models.schemas import SystemSettingsUpdate


REDIS_VERSION_KEY = "system_settings:version"
REDIS_CHANNEL = "system_settings_channel"
CACHE_TTL_SECONDS = 1.0


@dataclass
class RuntimeSystemSettings:
    """In-memory cached representation of active system settings."""
    reranker_threshold: float
    retrieval_top_k: int
    rerank_top_n: int
    history_messages: int
    rate_limit_per_minute: int
    rate_limit_login_per_minute: int
    sse_keepalive_interval: int
    max_upload_size_bytes: int
    version: int
    updated_at: datetime
    cached_at: float


class SystemSettingsManager:
    """Manages runtime system configuration, hot reloading, and audit logging."""

    def __init__(self):
        self._cached_settings: Optional[RuntimeSystemSettings] = None

    def invalidate_local_cache(self) -> None:
        """Clear local process cache."""
        self._cached_settings = None

    async def get_settings(self, force_refresh: bool = False) -> RuntimeSystemSettings:
        """Fetch active system settings, reloading from DB if version changed or cache expired."""
        now = time.monotonic()

        if not force_refresh and self._cached_settings is not None:
            if (now - self._cached_settings.cached_at) < CACHE_TTL_SECONDS:
                return self._cached_settings

            try:
                redis_client = get_redis_client()
                cached_ver_str = await redis_client.get(REDIS_VERSION_KEY)
                if cached_ver_str is not None:
                    current_redis_version = int(cached_ver_str)
                    if current_redis_version == self._cached_settings.version:
                        self._cached_settings.cached_at = now
                        return self._cached_settings
            except Exception:
                # If Redis is down, return currently cached settings
                return self._cached_settings

        # Reload from PostgreSQL
        try:
            async with AsyncSessionLocal() as session:
                query = select(SystemSettings).where(SystemSettings.id == 1)
                result = await session.execute(query)
                row = result.scalar_one_or_none()

                if not row:
                    # Seed initial singleton row from environment settings
                    row = SystemSettings(
                        id=1,
                        reranker_threshold=env_settings.RERANK_THRESHOLD,
                        retrieval_top_k=env_settings.RETRIEVAL_TOP_K,
                        rerank_top_n=env_settings.RERANK_TOP_N,
                        history_messages=env_settings.HISTORY_MESSAGES,
                        rate_limit_per_minute=env_settings.RATE_LIMIT_PER_MINUTE,
                        rate_limit_login_per_minute=env_settings.RATE_LIMIT_LOGIN_PER_MINUTE,
                        sse_keepalive_interval=env_settings.SSE_KEEPALIVE_INTERVAL,
                        max_upload_size_bytes=env_settings.MAX_UPLOAD_MB * 1024 * 1024,
                        version=1,
                        updated_at=datetime.now(timezone.utc),
                    )
                    session.add(row)
                    await session.commit()
                    await session.refresh(row)

                runtime = RuntimeSystemSettings(
                    reranker_threshold=float(row.reranker_threshold),
                    retrieval_top_k=int(row.retrieval_top_k),
                    rerank_top_n=int(row.rerank_top_n),
                    history_messages=int(row.history_messages),
                    rate_limit_per_minute=int(row.rate_limit_per_minute),
                    rate_limit_login_per_minute=int(row.rate_limit_login_per_minute),
                    sse_keepalive_interval=int(row.sse_keepalive_interval),
                    max_upload_size_bytes=int(row.max_upload_size_bytes),
                    version=int(row.version),
                    updated_at=row.updated_at,
                    cached_at=now,
                )
                self._cached_settings = runtime

                # Try updating Redis version key
                try:
                    redis_client = get_redis_client()
                    await redis_client.set(REDIS_VERSION_KEY, str(runtime.version))
                except Exception:
                    pass

                return runtime
        except Exception as e:
            logger.error(f"Error loading system_settings from DB: {e}. Falling back to config.")
            return RuntimeSystemSettings(
                reranker_threshold=env_settings.RERANK_THRESHOLD,
                retrieval_top_k=env_settings.RETRIEVAL_TOP_K,
                rerank_top_n=env_settings.RERANK_TOP_N,
                history_messages=env_settings.HISTORY_MESSAGES,
                rate_limit_per_minute=env_settings.RATE_LIMIT_PER_MINUTE,
                rate_limit_login_per_minute=env_settings.RATE_LIMIT_LOGIN_PER_MINUTE,
                sse_keepalive_interval=env_settings.SSE_KEEPALIVE_INTERVAL,
                max_upload_size_bytes=env_settings.MAX_UPLOAD_MB * 1024 * 1024,
                version=1,
                updated_at=datetime.now(timezone.utc),
                cached_at=now,
            )

    async def update_settings(
        self,
        updates: SystemSettingsUpdate,
        user_id: Optional[uuid.UUID] = None,
        user_email: Optional[str] = None,
        user: Optional[Any] = None,
    ) -> RuntimeSystemSettings:
        """Update runtime system settings, enforce bounds, create audit log, and broadcast version bump."""
        if user is not None:
            user_id = getattr(user, "id", user_id)
            user_email = getattr(user, "email", user_email)
        async with AsyncSessionLocal() as session:
            query = select(SystemSettings).where(SystemSettings.id == 1).with_for_update()
            result = await session.execute(query)
            row = result.scalar_one_or_none()

            if not row:
                row = SystemSettings(
                    id=1,
                    reranker_threshold=env_settings.RERANK_THRESHOLD,
                    retrieval_top_k=env_settings.RETRIEVAL_TOP_K,
                    rerank_top_n=env_settings.RERANK_TOP_N,
                    history_messages=env_settings.HISTORY_MESSAGES,
                    rate_limit_per_minute=env_settings.RATE_LIMIT_PER_MINUTE,
                    rate_limit_login_per_minute=env_settings.RATE_LIMIT_LOGIN_PER_MINUTE,
                    sse_keepalive_interval=env_settings.SSE_KEEPALIVE_INTERVAL,
                    max_upload_size_bytes=env_settings.MAX_UPLOAD_SIZE_BYTES,
                    version=1,
                    updated_at=datetime.now(timezone.utc),
                )
                session.add(row)

            # Capture old state for audit log diff
            old_state: Dict[str, Any] = {
                "reranker_threshold": float(row.reranker_threshold),
                "retrieval_top_k": int(row.retrieval_top_k),
                "rerank_top_n": int(row.rerank_top_n),
                "history_messages": int(row.history_messages),
                "rate_limit_per_minute": int(row.rate_limit_per_minute),
                "rate_limit_login_per_minute": int(row.rate_limit_login_per_minute),
                "sse_keepalive_interval": int(row.sse_keepalive_interval),
                "max_upload_size_bytes": int(row.max_upload_size_bytes),
            }

            # Proposed new state
            new_top_k = updates.retrieval_top_k if updates.retrieval_top_k is not None else row.retrieval_top_k
            new_top_n = updates.rerank_top_n if updates.rerank_top_n is not None else row.rerank_top_n

            if new_top_n > new_top_k:
                raise ValueError(
                    f"Reranker top_n ({new_top_n}) cannot exceed retrieval top_k ({new_top_k})."
                )

            # Detect if threshold was lowered below 0.50
            grounding_warning = None
            if updates.reranker_threshold is not None:
                if updates.reranker_threshold < 0.50 or updates.reranker_threshold < row.reranker_threshold:
                    grounding_warning = (
                        f"Lowering reranker threshold from {row.reranker_threshold:.2f} to "
                        f"{updates.reranker_threshold:.2f} weakens grounding and increases risk of hallucination."
                    )
                    logger.warning(
                        f"PROMINENT_SECURITY_WARNING: user={user_email or user_id} {grounding_warning}"
                    )

            # Apply updates
            if updates.reranker_threshold is not None:
                row.reranker_threshold = updates.reranker_threshold
            if updates.retrieval_top_k is not None:
                row.retrieval_top_k = updates.retrieval_top_k
            if updates.rerank_top_n is not None:
                row.rerank_top_n = updates.rerank_top_n
            if updates.history_messages is not None:
                row.history_messages = updates.history_messages
            if updates.rate_limit_per_minute is not None:
                row.rate_limit_per_minute = updates.rate_limit_per_minute
            if updates.rate_limit_login_per_minute is not None:
                row.rate_limit_login_per_minute = updates.rate_limit_login_per_minute
            if updates.sse_keepalive_interval is not None:
                row.sse_keepalive_interval = updates.sse_keepalive_interval
            if updates.max_upload_size_bytes is not None:
                row.max_upload_size_bytes = updates.max_upload_size_bytes

            row.version += 1
            row.updated_at = datetime.now(timezone.utc)

            new_state: Dict[str, Any] = {
                "reranker_threshold": float(row.reranker_threshold),
                "retrieval_top_k": int(row.retrieval_top_k),
                "rerank_top_n": int(row.rerank_top_n),
                "history_messages": int(row.history_messages),
                "rate_limit_per_minute": int(row.rate_limit_per_minute),
                "rate_limit_login_per_minute": int(row.rate_limit_login_per_minute),
                "sse_keepalive_interval": int(row.sse_keepalive_interval),
                "max_upload_size_bytes": int(row.max_upload_size_bytes),
            }

            # Create AuditLog record
            audit_entry = AuditLog(
                id=uuid.uuid4(),
                created_at=datetime.now(timezone.utc),
                user_id=user_id,
                user_email=user_email,
                action="UPDATE_SYSTEM_SETTINGS",
                target_type="system_settings",
                target_id="1",
                details={
                    "old": old_state,
                    "new": new_state,
                    "version": int(row.version),
                    "warning": grounding_warning,
                    "grounding_warning": bool(grounding_warning),
                },
            )
            session.add(audit_entry)

            await session.commit()
            await session.refresh(row)

            # Update cache and notify Redis
            runtime = RuntimeSystemSettings(
                reranker_threshold=float(row.reranker_threshold),
                retrieval_top_k=int(row.retrieval_top_k),
                rerank_top_n=int(row.rerank_top_n),
                history_messages=int(row.history_messages),
                rate_limit_per_minute=int(row.rate_limit_per_minute),
                rate_limit_login_per_minute=int(row.rate_limit_login_per_minute),
                sse_keepalive_interval=int(row.sse_keepalive_interval),
                max_upload_size_bytes=int(row.max_upload_size_bytes),
                version=int(row.version),
                updated_at=row.updated_at,
                cached_at=time.monotonic(),
            )
            self._cached_settings = runtime

            try:
                redis_client = get_redis_client()
                await redis_client.set(REDIS_VERSION_KEY, str(runtime.version))
                await redis_client.publish(REDIS_CHANNEL, str(runtime.version))
            except Exception as r_err:
                logger.warning(f"Failed to publish system settings update to Redis: {r_err}")

            logger.info(
                f"ADMIN_AUDIT: user_id={user_id} user_email={user_email} action=UPDATE_SYSTEM_SETTINGS "
                f"version={runtime.version}"
            )
            return runtime

    async def reset_to_defaults(
        self,
        user_id: Optional[uuid.UUID] = None,
        user_email: Optional[str] = None,
        user: Optional[Any] = None,
    ) -> RuntimeSystemSettings:
        """Reset all editable runtime system settings to environment baseline defaults."""
        if user is not None:
            user_id = getattr(user, "id", user_id)
            user_email = getattr(user, "email", user_email)

        defaults = SystemSettingsUpdate(
            reranker_threshold=env_settings.RERANK_THRESHOLD,
            retrieval_top_k=env_settings.RETRIEVAL_TOP_K,
            rerank_top_n=env_settings.RERANK_TOP_N,
            history_messages=env_settings.HISTORY_MESSAGES,
            rate_limit_per_minute=env_settings.RATE_LIMIT_PER_MINUTE,
            rate_limit_login_per_minute=env_settings.RATE_LIMIT_LOGIN_PER_MINUTE,
            sse_keepalive_interval=env_settings.SSE_KEEPALIVE_INTERVAL,
            max_upload_size_bytes=env_settings.MAX_UPLOAD_MB * 1024 * 1024,
        )

        res = await self.update_settings(defaults, user_id=user_id, user_email=user_email)

        # Record specific RESET action in audit log
        try:
            async with AsyncSessionLocal() as session:
                audit = AuditLog(
                    id=uuid.uuid4(),
                    created_at=datetime.now(timezone.utc),
                    user_id=user_id,
                    user_email=user_email,
                    action="RESET_SYSTEM_SETTINGS",
                    target_type="system_settings",
                    target_id="1",
                    details={
                        "version": res.version,
                        "reset_to": {
                            "reranker_threshold": res.reranker_threshold,
                            "retrieval_top_k": res.retrieval_top_k,
                            "rerank_top_n": res.rerank_top_n,
                            "history_messages": res.history_messages,
                            "rate_limit_per_minute": res.rate_limit_per_minute,
                            "rate_limit_login_per_minute": res.rate_limit_login_per_minute,
                            "sse_keepalive_interval": res.sse_keepalive_interval,
                            "max_upload_size_bytes": res.max_upload_size_bytes,
                        },
                    },
                )
                session.add(audit)
                await session.commit()
        except Exception as e:
            logger.warning(f"Failed to record RESET_SYSTEM_SETTINGS audit log: {e}")

        return res


system_settings_manager = SystemSettingsManager()
