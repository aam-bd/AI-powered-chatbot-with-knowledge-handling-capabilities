"""Redis session manager for conversation memory.

Implements Architecture §7, §8, and Prompt 4:
- Redis key: session:{user_id}:{session_id}
- User session index: user_sessions:{user_id}
- History window: last HISTORY_MESSAGES messages (default 6) via LTRIM
- Sliding TTL: SESSION_TTL_HOURS (default 24h) refreshed on every turn
- Kind markers: stores normal, fallback, and clarify message kinds
- Graceful degradation: if Redis is down, chat continues without memory and failure is logged
"""
import json
import time
from datetime import datetime, timezone
from typing import List, Optional
import redis.asyncio as aioredis

from app.core.config import settings
from app.core.logger import logger
from app.db.redis import redis_client
from app.models.schemas import ChatMessage, MessageKind, SessionSummaryResponse


class SessionManager:
    """Manages multi-turn conversation memory and session lifecycles in Redis."""

    def __init__(self, client: Optional[aioredis.Redis] = None):
        self._redis = client or redis_client

    def _session_key(self, user_id: str, session_id: str) -> str:
        """Construct Redis key for a specific user and session."""
        return f"session:{user_id}:{session_id}"

    def _user_sessions_key(self, user_id: str) -> str:
        """Construct Redis sorted set key tracking all sessions for a user."""
        return f"user_sessions:{user_id}"

    async def append_message(
        self,
        user_id: str,
        session_id: str,
        role: str,
        content: str,
        kind: MessageKind = MessageKind.NORMAL,
    ) -> None:
        """Append a message turn to the session history with sliding TTL and size cap.

        If Redis is down, logs a warning and allows chat to proceed without failing.
        """
        key = self._session_key(user_id, session_id)
        index_key = self._user_sessions_key(user_id)
        ttl_seconds = int(settings.SESSION_TTL_HOURS * 3600)
        now_ts = time.time()

        message = ChatMessage(
            role=role,
            content=content,
            kind=kind,
            created_at=datetime.now(timezone.utc),
        )
        msg_json = message.model_dump_json()

        try:
            # 1. Append message to the end of the list
            await self._redis.rpush(key, msg_json)

            # 2. Trim list to retain only the last HISTORY_MESSAGES
            max_history = int(settings.HISTORY_MESSAGES)
            await self._redis.ltrim(key, -max_history, -1)

            # 3. Refresh sliding TTL
            await self._redis.expire(key, ttl_seconds)

            # 4. Update user session index with current timestamp
            await self._redis.zadd(index_key, {session_id: now_ts})
            await self._redis.expire(index_key, ttl_seconds * 30)  # Keep index longer than sessions
        except Exception as exc:
            logger.warning(
                f"Redis failure in append_message for user {user_id}, session {session_id}: {exc}. "
                "Continuing chat without memory."
            )

    async def get_history(
        self,
        user_id: str,
        session_id: str,
    ) -> List[ChatMessage]:
        """Retrieve recent conversation history for a session.

        Returns empty list if session does not exist or if Redis is down.
        """
        key = self._session_key(user_id, session_id)
        try:
            raw_items = await self._redis.lrange(key, 0, -1)
            messages: List[ChatMessage] = []
            for item in raw_items:
                try:
                    data = json.loads(item)
                    messages.append(ChatMessage.model_validate(data))
                except Exception as parse_err:
                    logger.warning(f"Failed to parse chat message JSON from Redis: {parse_err}")
            return messages
        except Exception as exc:
            logger.warning(
                f"Redis failure in get_history for user {user_id}, session {session_id}: {exc}. "
                "Returning empty history."
            )
            return []

    async def get_history_for_router(
        self,
        user_id: str,
        session_id: str,
    ) -> List[ChatMessage]:
        """Retrieve conversation history tailored for the intent router.

        Returns history where fallback/clarification messages are flagged or filtered
        so the rewriter never treats negative fallback replies as factual knowledge.
        """
        history = await self.get_history(user_id, session_id)
        # We pass all turns to the router, but preserve the `kind` marker so the prompt
        # can explicitly instruct the LLM to ignore fallback responses as knowledge.
        return history

    async def list_sessions(
        self,
        user_id: str,
    ) -> List[SessionSummaryResponse]:
        """List active sessions for a user, ordered from most to least recently active."""
        index_key = self._user_sessions_key(user_id)
        summaries: List[SessionSummaryResponse] = []

        try:
            # Query session IDs and scores (timestamps) descending
            session_entries = await self._redis.zrevrange(index_key, 0, -1, withscores=True)
            for session_id, score in session_entries:
                key = self._session_key(user_id, session_id)
                exists = await self._redis.exists(key)
                if not exists:
                    # Clean up expired session from index
                    await self._redis.zrem(index_key, session_id)
                    continue

                # Fetch last message preview and total count
                msg_count = await self._redis.llen(key)
                last_items = await self._redis.lrange(key, -1, -1)
                preview = None
                if last_items:
                    try:
                        last_data = json.loads(last_items[0])
                        preview = last_data.get("content", "")[:100]
                    except Exception:
                        preview = None

                updated_at = datetime.fromtimestamp(score, tz=timezone.utc)
                summaries.append(
                    SessionSummaryResponse(
                        session_id=session_id,
                        message_count=msg_count,
                        last_message_preview=preview,
                        updated_at=updated_at,
                    )
                )
            return summaries
        except Exception as exc:
            logger.warning(f"Redis failure in list_sessions for user {user_id}: {exc}")
            return []

    async def clear_session(
        self,
        user_id: str,
        session_id: str,
    ) -> bool:
        """Clear an active chat session.

        Enforces strict user ownership isolation: user A can only clear their own session.
        Returns True if session was cleared, False if it was not found or failed.
        """
        key = self._session_key(user_id, session_id)
        index_key = self._user_sessions_key(user_id)

        try:
            exists = await self._redis.exists(key)
            if not exists:
                # Also remove from index if present
                await self._redis.zrem(index_key, session_id)
                return False

            await self._redis.delete(key)
            await self._redis.zrem(index_key, session_id)
            logger.info(f"Session {session_id} cleared for user {user_id}")
            return True
        except Exception as exc:
            logger.warning(f"Redis failure in clear_session for user {user_id}, session {session_id}: {exc}")
            return False


_session_manager_instance: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Return the global SessionManager singleton."""
    global _session_manager_instance
    if _session_manager_instance is None:
        _session_manager_instance = SessionManager()
    return _session_manager_instance
