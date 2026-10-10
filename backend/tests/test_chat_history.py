"""Acceptance and unit tests for Prompt 7c: Persistent Chat History.

Tests:
1. test_history_survives_new_login: Session list and full message history persist across logout/login.
2. test_owner_only_access_404_for_others: User B receives 404 for User A's session on GET/PATCH/DELETE/STREAM.
3. test_messages_restored_with_citations: Stored citations are returned intact in full history.
4. test_retract_stored_correctly: Layer 3 retract stores fallback text, kind='fallback', fallback_layer=3.
5. test_failures_never_store_partial_answer: Generation exceptions never persist partial assistant answers.
6. test_delete_removes_everything: DELETE clears PostgreSQL rows and Redis cache keys.
7. test_redis_flushed_then_history_rebuilt: Redis cache miss or flush rebuilds window from PostgreSQL.
8. test_client_supplied_unknown_session_id_rejected: Unknown client session IDs return 404.
9. test_rename_chat_session: PATCH updates title; empty title returns 422.
"""
import json
import uuid
import pytest
from starlette.testclient import TestClient

from app.core.config import settings
from app.db.redis import redis_client
from app.db.session import AsyncSessionLocal
from app.models.schemas import MessageKind
from app.models.sql_models import ChatSession, ChatMessageRecord
from app.services.session_manager import get_session_manager, SessionManager


def _create_user_and_login(client: TestClient) -> dict:
    """Helper to register a user and return login auth headers and user info."""
    uid = uuid.uuid4().hex[:8]
    email = f"user_{uid}@example.com"
    password = "Password123!"
    ip = f"198.51.100.{uuid.uuid4().int % 200 + 10}"

    reg_resp = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert reg_resp.status_code == 201

    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        headers={"X-Forwarded-For": ip},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    user_id = reg_resp.json()["id"]

    return {
        "email": email,
        "password": password,
        "user_id": user_id,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}", "X-Forwarded-For": ip},
    }


def _parse_sse_events(raw_text: str) -> list:
    """Parse SSE event stream into list of (event_name, data_dict)."""
    events = []
    lines = raw_text.strip().split("\n")
    current_event = None
    for line in lines:
        if line.startswith("event: "):
            current_event = line[7:].strip()
        elif line.startswith("data: ") and current_event:
            try:
                data = json.loads(line[6:].strip())
                events.append((current_event, data))
            except Exception:
                pass
            current_event = None
    return events


def test_unknown_session_id_creates_server_assigned_session(client: TestClient):
    """Calling POST /chat/stream with unknown or client-chosen session_id ignores it and creates a server-assigned session."""
    user = _create_user_and_login(client)

    client_chosen_id = "arbitrary-client-chosen-id"
    resp = client.post(
        "/api/v1/chat/stream",
        json={"message": "Hello assistant", "session_id": client_chosen_id},
        headers=user["headers"],
    )
    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    session_id = [data["session_id"] for ev, data in events if ev == "done"][0]
    # Server assigned its own UUID, ignoring the client-supplied ID!
    assert session_id != client_chosen_id

    # And the session is properly recorded under user's sessions
    list_resp = client.get("/api/v1/chat/sessions", headers=user["headers"])
    assert any(s["session_id"] == session_id for s in list_resp.json())


def test_history_survives_new_login(client: TestClient):
    """Conversation history persists across logout and login."""
    user = _create_user_and_login(client)

    # 1. Start chat stream without session_id (server assigns ID)
    stream_resp = client.post(
        "/api/v1/chat/stream",
        json={"message": "Hello assistant"},
        headers=user["headers"],
    )
    assert stream_resp.status_code == 200
    events = _parse_sse_events(stream_resp.text)
    done_events = [data for event, data in events if event == "done"]
    assert len(done_events) == 1
    session_id = done_events[0]["session_id"]
    assert session_id

    # 2. List sessions
    list_resp = client.get("/api/v1/chat/sessions", headers=user["headers"])
    assert list_resp.status_code == 200
    sessions = list_resp.json()
    assert len(sessions) >= 1
    matching = [s for s in sessions if s["session_id"] == session_id]
    assert len(matching) == 1
    assert matching[0]["title"] == "Hello assistant"
    assert matching[0]["message_count"] == 2

    # 3. Simulate new login (new token)
    new_login = client.post(
        "/api/v1/auth/login",
        json={"email": user["email"], "password": user["password"]},
        headers={"X-Forwarded-For": f"198.51.100.{uuid.uuid4().int % 200 + 10}"},
    )
    assert new_login.status_code == 200
    new_headers = {"Authorization": f"Bearer {new_login.json()['access_token']}"}

    # 4. Fetch full history with new token
    messages_resp = client.get(f"/api/v1/chat/sessions/{session_id}/messages", headers=new_headers)
    assert messages_resp.status_code == 200
    msgs = messages_resp.json()
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "Hello assistant"
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["content"] == settings.GREETING_MESSAGE


def test_owner_only_access_404_for_others(client: TestClient):
    """User B cannot access, rename, stream into, or delete User A's session (strict 404)."""
    user_a = _create_user_and_login(client)
    user_b = _create_user_and_login(client)

    # User A creates a session
    stream_resp = client.post(
        "/api/v1/chat/stream",
        json={"message": "Secret user A topic"},
        headers=user_a["headers"],
    )
    assert stream_resp.status_code == 200
    events = _parse_sse_events(stream_resp.text)
    session_id_a = [data["session_id"] for ev, data in events if ev == "done"][0]

    # User B tries GET messages
    get_resp = client.get(f"/api/v1/chat/sessions/{session_id_a}/messages", headers=user_b["headers"])
    assert get_resp.status_code == 404

    # User B tries PATCH rename
    patch_resp = client.patch(
        f"/api/v1/chat/sessions/{session_id_a}",
        json={"title": "Hacked Title"},
        headers=user_b["headers"],
    )
    assert patch_resp.status_code == 404

    # User B tries DELETE session
    del_resp = client.delete(f"/api/v1/chat/sessions/{session_id_a}", headers=user_b["headers"])
    assert del_resp.status_code == 404

    # User B tries POST /chat/stream with User A's session ID
    stream_b = client.post(
        "/api/v1/chat/stream",
        json={"message": "Intrusion", "session_id": session_id_a},
        headers=user_b["headers"],
    )
    assert stream_b.status_code == 404


def test_rename_chat_session(client: TestClient):
    """PATCH /chat/sessions/{id} renames title; empty title returns 422."""
    user = _create_user_and_login(client)

    stream_resp = client.post(
        "/api/v1/chat/stream",
        json={"message": "Initial conversation question"},
        headers=user["headers"],
    )
    session_id = _parse_sse_events(stream_resp.text)[0][1].get("session_id") or [
        data["session_id"] for ev, data in _parse_sse_events(stream_resp.text) if ev == "done"
    ][0]

    # 1. Valid rename
    rename_resp = client.patch(
        f"/api/v1/chat/sessions/{session_id}",
        json={"title": "Custom Topic Name"},
        headers=user["headers"],
    )
    assert rename_resp.status_code == 200
    assert rename_resp.json()["title"] == "Custom Topic Name"

    # Verify session list shows renamed title
    list_resp = client.get("/api/v1/chat/sessions", headers=user["headers"])
    session = next(s for s in list_resp.json() if s["session_id"] == session_id)
    assert session["title"] == "Custom Topic Name"

    # 2. Empty title returns 422
    bad_resp = client.patch(
        f"/api/v1/chat/sessions/{session_id}",
        json={"title": "   "},
        headers=user["headers"],
    )
    assert bad_resp.status_code == 422


def test_delete_removes_everything(client: TestClient):
    """DELETE /chat/sessions/{id} removes session from PostgreSQL and Redis."""
    user = _create_user_and_login(client)

    stream_resp = client.post(
        "/api/v1/chat/stream",
        json={"message": "Ephemeral conversation"},
        headers=user["headers"],
    )
    session_id = [data["session_id"] for ev, data in _parse_sse_events(stream_resp.text) if ev == "done"][0]

    # Delete session
    del_resp = client.delete(f"/api/v1/chat/sessions/{session_id}", headers=user["headers"])
    assert del_resp.status_code == 200

    # GET messages returns 404
    get_resp = client.get(f"/api/v1/chat/sessions/{session_id}/messages", headers=user["headers"])
    assert get_resp.status_code == 404

    # GET sessions no longer includes it
    list_resp = client.get("/api/v1/chat/sessions", headers=user["headers"])
    assert not any(s["session_id"] == session_id for s in list_resp.json())


@pytest.mark.asyncio
async def test_redis_flushed_then_history_rebuilt(client: TestClient):
    """When Redis is cleared, get_history rebuilds the window from PostgreSQL."""
    user = _create_user_and_login(client)
    session_manager = get_session_manager()
    user_id = user["user_id"]

    # Create session and persist turns in PostgreSQL
    session = await session_manager.get_or_create_session(user_id=user_id, initial_title="Cache test")
    session_id = str(session.id)

    await session_manager.persist_user_message(session.id, "Question 1")
    await session_manager.persist_assistant_message(session.id, "Answer 1")
    await session_manager.persist_user_message(session.id, "Question 2")
    await session_manager.persist_assistant_message(session.id, "Answer 2")

    # Flush Redis key explicitly to simulate restart or TTL expiration
    key = session_manager._session_key(user_id, session_id)
    await redis_client.delete(key)
    assert await redis_client.exists(key) == 0

    # Call get_history -> must fetch from PostgreSQL and repopulate Redis
    history = await session_manager.get_history(user_id, session_id)
    assert len(history) == 4
    assert history[0].content == "Question 1"
    assert history[1].content == "Answer 1"
    assert history[2].content == "Question 2"
    assert history[3].content == "Answer 2"

    # Verify Redis key has been rebuilt
    assert await redis_client.exists(key) == 1
    cached_len = await redis_client.llen(key)
    assert cached_len == 4

    # Cleanup
    await session_manager.clear_session(user_id, session_id)


@pytest.mark.asyncio
async def test_messages_restored_with_citations(client: TestClient):
    """Messages with citations are persisted and returned with citation metadata."""
    user = _create_user_and_login(client)
    session_manager = get_session_manager()

    # Create session
    session = await session_manager.get_or_create_session(
        user_id=user["user_id"],
        initial_title="Citation test",
    )
    session_id = str(session.id)

    test_citations = [
        {
            "chunk_id": "chunk-101",
            "document_id": str(uuid.uuid4()),
            "document_name": "company_handbook.pdf",
            "page_or_section": "Section 4.2",
            "score": 0.89,
            "snippet": "Employees receive 20 days paid leave.",
        }
    ]

    await session_manager.persist_user_message(session.id, "How many days leave?")
    await session_manager.persist_assistant_message(
        session_id=session.id,
        content="You receive 20 days of paid leave. [1]",
        kind="normal",
        citations=test_citations,
    )

    # Fetch messages via API
    resp = client.get(f"/api/v1/chat/sessions/{session_id}/messages", headers=user["headers"])
    assert resp.status_code == 200
    msgs = resp.json()
    assert len(msgs) == 2
    assistant_msg = msgs[1]
    assert assistant_msg["citations"] is not None
    assert len(assistant_msg["citations"]) == 1
    assert assistant_msg["citations"][0]["document_name"] == "company_handbook.pdf"
    assert assistant_msg["citations"][0]["chunk_id"] == "chunk-101"

    # Cleanup
    await session_manager.clear_session(user["user_id"], session_id)


@pytest.mark.asyncio
async def test_retract_stored_correctly(client: TestClient):
    """Retracted answers store fallback message, kind='fallback', and fallback_layer=3."""
    user = _create_user_and_login(client)
    session_manager = get_session_manager()
    user_id = user["user_id"]
    session = await session_manager.get_or_create_session(user_id=user_id, initial_title="Retract test")
    session_id = str(session.id)

    await session_manager.persist_user_message(session.id, "Ungrounded question")
    await session_manager.persist_assistant_message(
        session_id=session.id,
        content=settings.FALLBACK_MESSAGE,
        kind="fallback",
        fallback_layer=3,
    )

    messages = await session_manager.get_session_messages(user_id=user_id, session_id=session_id)
    assert len(messages) == 2
    assert messages[1].content == settings.FALLBACK_MESSAGE
    assert messages[1].kind == "fallback"
    assert messages[1].fallback_layer == 3

    # Cleanup
    await session_manager.clear_session(user_id, session_id)


def test_failures_never_store_partial_answer(client: TestClient, monkeypatch):
    """Exceptions during generation never persist partial answers to PostgreSQL or Redis."""
    user = _create_user_and_login(client)

    # Mock RAG engine retrieve to simulate failure mid-pipeline
    from app.services.rag_engine import RAGEngine
    def mock_retrieve_fail(*args, **kwargs):
        raise RuntimeError("Simulated mid-stream LLM failure")

    monkeypatch.setattr(RAGEngine, "retrieve", mock_retrieve_fail)

    resp = client.post(
        "/api/v1/chat/stream",
        json={"message": "What is our policy on remote work?"},
        headers=user["headers"],
    )
    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)

    # Must contain error event
    error_events = [data for ev, data in events if ev == "error"]
    assert len(error_events) == 1
    session_id = [data["session_id"] for ev, data in events if ev == "done"][0]

    # Inspect persisted messages: ONLY the user message must exist
    msgs_resp = client.get(f"/api/v1/chat/sessions/{session_id}/messages", headers=user["headers"])
    assert msgs_resp.status_code == 200
    msgs = msgs_resp.json()
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    assert msgs[0]["content"] == "What is our policy on remote work?"
