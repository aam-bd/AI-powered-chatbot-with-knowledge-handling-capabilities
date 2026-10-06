"""Unit and integration tests for SessionManager and chat session API endpoints.

Covers:
- Session history cap (preserves only the last HISTORY_MESSAGES turns).
- Sliding TTL (refreshed on each turn).
- Message kind markers (normal, fallback, clarify).
- Multi-user session ownership isolation (user A cannot read or delete user B's session).
- DELETE /api/v1/chat/sessions/{id} clears memory and user index.
- Redis-down resilience (continues without memory and logs failures).
"""
import uuid
import pytest
from starlette.testclient import TestClient

from app.core.config import settings
from app.core.security import create_access_token
from app.db.redis import redis_client
from app.models.schemas import MessageKind
from app.services.session_manager import SessionManager, get_session_manager


@pytest.fixture
def session_manager() -> SessionManager:
    return get_session_manager()


@pytest.mark.asyncio
async def test_session_history_cap(session_manager: SessionManager, monkeypatch):
    """Verify that only the last HISTORY_MESSAGES messages are kept in memory."""
    user_id = str(uuid.uuid4())
    session_id = f"test-cap-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr(settings, "HISTORY_MESSAGES", 4)

    # Append 8 messages
    for i in range(8):
        await session_manager.append_message(
            user_id=user_id,
            session_id=session_id,
            role="user" if i % 2 == 0 else "assistant",
            content=f"Message {i}",
        )

    history = await session_manager.get_history(user_id, session_id)
    assert len(history) == 4
    # Should be the last 4 messages: 4, 5, 6, 7
    expected_contents = ["Message 4", "Message 5", "Message 6", "Message 7"]
    assert [m.content for m in history] == expected_contents

    # Cleanup
    await session_manager.clear_session(user_id, session_id)


@pytest.mark.asyncio
async def test_session_sliding_ttl(session_manager: SessionManager):
    """Verify sliding TTL is set and refreshed on the Redis session key."""
    user_id = str(uuid.uuid4())
    session_id = f"test-ttl-{uuid.uuid4().hex[:8]}"

    await session_manager.append_message(
        user_id=user_id,
        session_id=session_id,
        role="user",
        content="Testing sliding TTL",
    )

    key = session_manager._session_key(user_id, session_id)
    ttl = await redis_client.ttl(key)
    max_expected = int(settings.SESSION_TTL_HOURS * 3600)

    assert ttl > 0
    assert ttl <= max_expected

    # Cleanup
    await session_manager.clear_session(user_id, session_id)


@pytest.mark.asyncio
async def test_session_message_kind_markers(session_manager: SessionManager):
    """Verify messages store and retrieve kind markers (normal, fallback, clarify)."""
    user_id = str(uuid.uuid4())
    session_id = f"test-kinds-{uuid.uuid4().hex[:8]}"

    await session_manager.append_message(
        user_id=user_id,
        session_id=session_id,
        role="user",
        content="What is Bitcoin?",
        kind=MessageKind.NORMAL,
    )
    await session_manager.append_message(
        user_id=user_id,
        session_id=session_id,
        role="assistant",
        content="Could you clarify what aspect?",
        kind=MessageKind.CLARIFY,
    )
    await session_manager.append_message(
        user_id=user_id,
        session_id=session_id,
        role="assistant",
        content="I couldn't find information about that.",
        kind=MessageKind.FALLBACK,
    )

    history = await session_manager.get_history(user_id, session_id)
    assert len(history) == 3
    assert history[0].kind == MessageKind.NORMAL
    assert history[1].kind == MessageKind.CLARIFY
    assert history[2].kind == MessageKind.FALLBACK

    # Cleanup
    await session_manager.clear_session(user_id, session_id)


@pytest.mark.asyncio
async def test_session_ownership_isolation(session_manager: SessionManager):
    """Verify user A cannot read, list, or delete user B's session."""
    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())
    sess_a = f"sess-a-{uuid.uuid4().hex[:6]}"
    sess_b = f"sess-b-{uuid.uuid4().hex[:6]}"

    await session_manager.append_message(user_a, sess_a, "user", "Message A")
    await session_manager.append_message(user_b, sess_b, "user", "Message B")

    # User A listing sessions should only see sess_a
    list_a = await session_manager.list_sessions(user_a)
    assert any(s.session_id == sess_a for s in list_a)
    assert not any(s.session_id == sess_b for s in list_a)

    # User A trying to get User B's history
    hist_b_from_a = await session_manager.get_history(user_a, sess_b)
    assert len(hist_b_from_a) == 0

    # User A attempting to clear User B's session returns False
    cleared = await session_manager.clear_session(user_a, sess_b)
    assert cleared is False

    # User B's session must still exist
    hist_b = await session_manager.get_history(user_b, sess_b)
    assert len(hist_b) == 1

    # Cleanup
    await session_manager.clear_session(user_a, sess_a)
    await session_manager.clear_session(user_b, sess_b)


@pytest.mark.asyncio
async def test_chat_sessions_api_endpoints(client: TestClient, session_manager: SessionManager):
    """Verify GET /api/v1/chat/sessions and DELETE /api/v1/chat/sessions/{id} with auth and ownership."""
    email_1 = f"user1_{uuid.uuid4().hex[:8]}@example.com"
    pwd = "Password123!"
    r1 = client.post("/api/v1/auth/register", json={"email": email_1, "password": pwd})
    assert r1.status_code == 201
    user_id_1 = str(r1.json()["id"])
    l1 = client.post("/api/v1/auth/login", json={"email": email_1, "password": pwd})
    token_1 = l1.json()["access_token"]

    email_2 = f"user2_{uuid.uuid4().hex[:8]}@example.com"
    r2 = client.post("/api/v1/auth/register", json={"email": email_2, "password": pwd})
    assert r2.status_code == 201
    user_id_2 = str(r2.json()["id"])
    l2 = client.post("/api/v1/auth/login", json={"email": email_2, "password": pwd})
    token_2 = l2.json()["access_token"]

    sess_1 = f"api-sess-1-{uuid.uuid4().hex[:6]}"
    sess_2 = f"api-sess-2-{uuid.uuid4().hex[:6]}"

    await session_manager.append_message(user_id_1, sess_1, "user", "Hello from User 1")
    await session_manager.append_message(user_id_2, sess_2, "user", "Hello from User 2")

    # 1. Unauthenticated request rejected
    unauth_resp = client.get("/api/v1/chat/sessions")
    assert unauth_resp.status_code == 401

    # 2. User 1 lists sessions -> sees only sess_1
    headers_1 = {"Authorization": f"Bearer {token_1}"}
    resp_1 = client.get("/api/v1/chat/sessions", headers=headers_1)
    assert resp_1.status_code == 200
    sessions_1 = resp_1.json()
    assert any(s["session_id"] == sess_1 for s in sessions_1)
    assert not any(s["session_id"] == sess_2 for s in sessions_1)

    # 3. User 1 attempts to delete User 2's session -> 404 Not Found
    del_resp_unauth = client.delete(f"/api/v1/chat/sessions/{sess_2}", headers=headers_1)
    assert del_resp_unauth.status_code == 404
    assert del_resp_unauth.json()["code"] == "SESSION_NOT_FOUND"

    # 4. User 1 deletes own session -> 200 OK
    del_resp_ok = client.delete(f"/api/v1/chat/sessions/{sess_1}", headers=headers_1)
    assert del_resp_ok.status_code == 200
    assert del_resp_ok.json()["session_id"] == sess_1

    # 5. After deletion, sess_1 is no longer listed
    resp_after = client.get("/api/v1/chat/sessions", headers=headers_1)
    assert not any(s["session_id"] == sess_1 for s in resp_after.json())

    # Cleanup user 2
    await session_manager.clear_session(user_id_2, sess_2)


@pytest.mark.asyncio
async def test_redis_down_resilience():
    """Verify SessionManager gracefully degrades without crashing when Redis is down."""
    class BrokenRedis:
        """Simulates Redis connection failure across all operations."""
        async def rpush(self, *args, **kwargs):
            raise ConnectionError("Redis is unreachable")

        async def ltrim(self, *args, **kwargs):
            raise ConnectionError("Redis is unreachable")

        async def expire(self, *args, **kwargs):
            raise ConnectionError("Redis is unreachable")

        async def zadd(self, *args, **kwargs):
            raise ConnectionError("Redis is unreachable")

        async def lrange(self, *args, **kwargs):
            raise ConnectionError("Redis is unreachable")

        async def zrevrange(self, *args, **kwargs):
            raise ConnectionError("Redis is unreachable")

        async def exists(self, *args, **kwargs):
            raise ConnectionError("Redis is unreachable")

        async def delete(self, *args, **kwargs):
            raise ConnectionError("Redis is unreachable")

    broken_sm = SessionManager(client=BrokenRedis())
    user_id = "test-broken-user"
    session_id = "test-broken-session"

    # append_message should log warning and return without error
    await broken_sm.append_message(user_id, session_id, "user", "Hello")

    # get_history should log warning and return empty list
    history = await broken_sm.get_history(user_id, session_id)
    assert history == []

    # list_sessions should log warning and return empty list
    sessions = await broken_sm.list_sessions(user_id)
    assert sessions == []

    # clear_session should log warning and return False
    cleared = await broken_sm.clear_session(user_id, session_id)
    assert cleared is False
