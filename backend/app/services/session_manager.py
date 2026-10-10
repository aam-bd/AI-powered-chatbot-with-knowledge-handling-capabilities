"""Session manager for persistent conversation memory and Redis caching.

Implements Architecture §4.1, §7, §8, and Prompt 7c:
- Persistent history in PostgreSQL: chat_sessions and chat_messages
- Redis window cache: session:{user_id}:{session_id} with last HISTORY_MESSAGES and 24h sliding TTL
- Rebuild Redis cache from PostgreSQL when key is missing or Redis was flushed/restarted
- Owner-only access (404 for unowned or nonexistent sessions)
- Server-generated session IDs; client-chosen unknown IDs return 404
- Resilient persistence: DB errors never interrupt or break SSE streaming
"""
import json
import time
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Tuple
import redis.asyncio as aioredis
from fastapi import HTTPException, status
from sqlalchemy import select, func, update, delete

from app.core.config import settings
from app.core.logger import logger
from app.db.redis import redis_client
from app.db.session import AsyncSessionLocal
from app.models.schemas import (
    ChatMessage,
    MessageKind,
    SessionSummaryResponse,
    ChatMessageItemResponse,
)
from app.models.sql_models import (
    ChatSession,
    ChatMessageRecord,
    utcnow,
)


class SessionManager:
    """Manages multi-turn conversation memory across PostgreSQL and Redis."""

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
        """Append a message turn to the Redis session history with sliding TTL and size cap.

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
            await self._redis.expire(index_key, ttl_seconds * 30)
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

        Per §7 and Prompt 7c:
        - First checks Redis cache.
        - If key is missing or Redis is empty/flushed, rebuilds window from PostgreSQL.
        - If Redis is down, falls back directly to PostgreSQL.
        """
        key = self._session_key(user_id, session_id)
        redis_failed = False

        try:
            raw_items = await self._redis.lrange(key, 0, -1)
            if raw_items:
                messages: List[ChatMessage] = []
                for item in raw_items:
                    try:
                        data = json.loads(item)
                        messages.append(ChatMessage.model_validate(data))
                    except Exception as parse_err:
                        logger.warning(f"Failed to parse chat message JSON from Redis: {parse_err}")
                if messages:
                    return messages
        except Exception as exc:
            logger.warning(
                f"Redis failure in get_history for user {user_id}, session {session_id}: {exc}. "
                "Attempting fallback to PostgreSQL."
            )
            redis_failed = True

        # Cache miss or Redis unavailable: Rebuild from PostgreSQL
        try:
            u_uuid = uuid.UUID(user_id)
            s_uuid = uuid.UUID(session_id)
        except (ValueError, TypeError):
            return []

        try:
            async with AsyncSessionLocal() as db:
                stmt = (
                    select(ChatMessageRecord)
                    .join(ChatSession, ChatMessageRecord.session_id == ChatSession.id)
                    .where(ChatSession.id == s_uuid, ChatSession.user_id == u_uuid)
                    .order_by(ChatMessageRecord.created_at.desc())
                    .limit(int(settings.HISTORY_MESSAGES))
                )
                res = await db.execute(stmt)
                records = res.scalars().all()
                if not records:
                    return []

                # Restore chronological ordering
                ordered_records = list(reversed(records))
                messages = []
                for r in ordered_records:
                    k = MessageKind.NORMAL
                    try:
                        k = MessageKind(r.kind)
                    except ValueError:
                        pass
                    messages.append(
                        ChatMessage(
                            role=r.role,
                            content=r.content,
                            kind=k,
                            created_at=r.created_at,
                        )
                    )

                # Rebuild Redis cache if Redis is accessible
                if not redis_failed and messages:
                    try:
                        pipe = self._redis.pipeline()
                        for msg in messages:
                            pipe.rpush(key, msg.model_dump_json())
                        pipe.ltrim(key, -int(settings.HISTORY_MESSAGES), -1)
                        pipe.expire(key, int(settings.SESSION_TTL_HOURS * 3600))
                        await pipe.execute()
                        logger.info(
                            f"Rebuilt Redis history window ({len(messages)} msgs) from PostgreSQL for session {session_id}"
                        )
                    except Exception as rebuild_exc:
                        logger.warning(f"Failed to repopulate Redis from PostgreSQL: {rebuild_exc}")

                return messages
        except Exception as pg_exc:
            logger.warning(f"PostgreSQL failure in get_history for user {user_id}, session {session_id}: {pg_exc}")
            return []

    async def get_history_for_router(
        self,
        user_id: str,
        session_id: str,
    ) -> List[ChatMessage]:
        """Retrieve conversation history tailored for the intent router."""
        return await self.get_history(user_id, session_id)

    # --------------------------------------------------------------------------
    # PostgreSQL Persistent Session Operations
    # --------------------------------------------------------------------------

    async def get_or_create_session(
        self,
        user_id: str,
        session_id: Optional[str] = None,
        initial_title: Optional[str] = None,
    ) -> ChatSession:
        """Resolve an existing session with strict ownership check, or create a new one.

        Rules per §7 and Prompt 7c:
        - Unknown/nonexistent client-supplied session_id raises 404 (prevents client-chosen IDs).
        - Session owned by another user raises 404.
        - Empty/null session_id creates a new session for current user.
        - Title defaults to first user message truncated to 60 characters.
        """
        try:
            u_uuid = uuid.UUID(user_id)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid user ID.",
                headers={"code": "INVALID_USER"},
            )

        async with AsyncSessionLocal() as db:
            if session_id:
                try:
                    s_uuid = uuid.UUID(session_id)
                    res = await db.execute(
                        select(ChatSession).where(ChatSession.id == s_uuid)
                    )
                    existing = res.scalar_one_or_none()
                    if existing:
                        if existing.user_id != u_uuid:
                            raise HTTPException(
                                status_code=status.HTTP_404_NOT_FOUND,
                                detail="Session not found.",
                                headers={"code": "SESSION_NOT_FOUND"},
                            )
                        return existing
                    # If not found in DB: per Prompt 7c:
                    # "An unknown session_id creates a session for the current user; a session owned by someone else returns 404."
                    # "The server generates session IDs. Ignore any client-supplied ID that doesn't exist rather than creating a session with a client-chosen ID."
                except (ValueError, TypeError):
                    pass

            # Create fresh session with server-assigned UUID
            new_id = uuid.uuid4()
            title = (initial_title or "New Chat").strip()[:60] or "New Chat"
            new_session = ChatSession(
                id=new_id,
                user_id=u_uuid,
                title=title,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
            db.add(new_session)
            await db.commit()
            await db.refresh(new_session)
            return new_session

    async def persist_user_message(
        self,
        session_id: uuid.UUID,
        content: str,
    ) -> None:
        """Persist user message to PostgreSQL before generation starts."""
        try:
            async with AsyncSessionLocal() as db:
                msg = ChatMessageRecord(
                    session_id=session_id,
                    role="user",
                    kind="normal",
                    content=content,
                    created_at=utcnow(),
                )
                db.add(msg)
                await db.execute(
                    update(ChatSession)
                    .where(ChatSession.id == session_id)
                    .values(updated_at=utcnow())
                )
                await db.commit()
        except Exception as exc:
            logger.warning(f"Failed to persist user message in session {session_id}: {exc}")

    async def persist_assistant_message(
        self,
        session_id: uuid.UUID,
        content: str,
        kind: str = "normal",
        citations: Optional[list] = None,
        fallback_layer: Optional[int] = None,
    ) -> None:
        """Persist assistant message to PostgreSQL after generation completes."""
        try:
            async with AsyncSessionLocal() as db:
                msg = ChatMessageRecord(
                    session_id=session_id,
                    role="assistant",
                    kind=kind,
                    content=content,
                    citations=citations,
                    fallback_layer=fallback_layer,
                    created_at=utcnow(),
                )
                db.add(msg)
                await db.execute(
                    update(ChatSession)
                    .where(ChatSession.id == session_id)
                    .values(updated_at=utcnow())
                )
                await db.commit()
        except Exception as exc:
            logger.warning(f"Failed to persist assistant message in session {session_id}: {exc}")

    async def list_sessions(
        self,
        user_id: str,
    ) -> List[SessionSummaryResponse]:
        """List persistent sessions for a user, ordered newest first."""
        try:
            u_uuid = uuid.UUID(user_id)
        except (ValueError, TypeError):
            return []

        try:
            async with AsyncSessionLocal() as db:
                stmt = (
                    select(
                        ChatSession.id,
                        ChatSession.title,
                        ChatSession.created_at,
                        ChatSession.updated_at,
                        func.count(ChatMessageRecord.id).label("message_count"),
                    )
                    .outerjoin(ChatMessageRecord, ChatSession.id == ChatMessageRecord.session_id)
                    .where(ChatSession.user_id == u_uuid)
                    .group_by(ChatSession.id)
                    .order_by(ChatSession.updated_at.desc())
                )
                res = await db.execute(stmt)
                rows = res.all()
                return [
                    SessionSummaryResponse(
                        id=row.id,
                        session_id=str(row.id),
                        title=row.title,
                        message_count=row.message_count,
                        created_at=row.created_at,
                        updated_at=row.updated_at,
                    )
                    for row in rows
                ]
        except Exception as exc:
            logger.warning(f"PostgreSQL failure in list_sessions for user {user_id}: {exc}")
            return []

    async def get_session_messages(
        self,
        user_id: str,
        session_id: str,
    ) -> List[ChatMessageItemResponse]:
        """Retrieve full chronological conversation history with citations."""
        try:
            u_uuid = uuid.UUID(user_id)
            s_uuid = uuid.UUID(session_id)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found.",
                headers={"code": "SESSION_NOT_FOUND"},
            )

        async with AsyncSessionLocal() as db:
            # Check owner
            res = await db.execute(
                select(ChatSession.id).where(ChatSession.id == s_uuid, ChatSession.user_id == u_uuid)
            )
            if not res.scalar_one_or_none():
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Session not found.",
                    headers={"code": "SESSION_NOT_FOUND"},
                )

            stmt = (
                select(ChatMessageRecord)
                .where(ChatMessageRecord.session_id == s_uuid)
                .order_by(ChatMessageRecord.created_at.asc())
            )
            records = (await db.execute(stmt)).scalars().all()
            return [
                ChatMessageItemResponse(
                    id=r.id,
                    session_id=r.session_id,
                    role=r.role,
                    kind=r.kind,
                    content=r.content,
                    citations=r.citations,
                    fallback_layer=r.fallback_layer,
                    created_at=r.created_at,
                )
                for r in records
            ]

    async def rename_session(
        self,
        user_id: str,
        session_id: str,
        title: str,
    ) -> SessionSummaryResponse:
        """Rename conversation title (owner-only)."""
        try:
            u_uuid = uuid.UUID(user_id)
            s_uuid = uuid.UUID(session_id)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found.",
                headers={"code": "SESSION_NOT_FOUND"},
            )

        clean_title = title.strip()[:255]
        if not clean_title:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Title cannot be empty.",
                headers={"code": "INVALID_TITLE"},
            )

        async with AsyncSessionLocal() as db:
            res = await db.execute(
                select(ChatSession).where(ChatSession.id == s_uuid, ChatSession.user_id == u_uuid)
            )
            session = res.scalar_one_or_none()
            if not session:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Session not found.",
                    headers={"code": "SESSION_NOT_FOUND"},
                )

            session.title = clean_title
            session.updated_at = utcnow()
            await db.commit()
            await db.refresh(session)

            cnt = await db.scalar(
                select(func.count(ChatMessageRecord.id)).where(ChatMessageRecord.session_id == s_uuid)
            )
            return SessionSummaryResponse(
                id=session.id,
                session_id=str(session.id),
                title=session.title,
                message_count=cnt or 0,
                created_at=session.created_at,
                updated_at=session.updated_at,
            )

    async def clear_session(
        self,
        user_id: str,
        session_id: str,
    ) -> bool:
        """Delete conversation from PostgreSQL and Redis (owner-only)."""
        try:
            u_uuid = uuid.UUID(user_id)
            s_uuid = uuid.UUID(session_id)
        except (ValueError, TypeError):
            return False

        async with AsyncSessionLocal() as db:
            res = await db.execute(
                select(ChatSession).where(ChatSession.id == s_uuid, ChatSession.user_id == u_uuid)
            )
            session = res.scalar_one_or_none()
            if not session:
                return False

            await db.delete(session)
            await db.commit()

        # Delete Redis cache
        key = self._session_key(user_id, session_id)
        index_key = self._user_sessions_key(user_id)
        try:
            await self._redis.delete(key)
            await self._redis.zrem(index_key, session_id)
        except Exception as redis_err:
            logger.warning(f"Could not delete Redis keys for session {session_id}: {redis_err}")

        logger.info(f"Session {session_id} deleted for user {user_id}")
        return True


_session_manager_instance: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Return the global SessionManager singleton."""
    global _session_manager_instance
    if _session_manager_instance is None:
        _session_manager_instance = SessionManager()
    return _session_manager_instance
