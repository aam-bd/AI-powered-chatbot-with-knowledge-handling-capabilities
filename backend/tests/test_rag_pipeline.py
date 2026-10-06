"""Comprehensive acceptance test suite for the RAG chat pipeline.

Implements Prompt 4 Acceptance tests:
1. Pure greeting path (returns canned GREETING_MESSAGE, done intent=GREETING)
2. Clarification path (returns clarification question, done intent=CLARIFY)
3. Follow-up rewrite using history (rewrites pronoun query, searches, streams answer and citations)
4. Layer 1 fallback (rerank score below threshold returns FALLBACK_MESSAGE, fallback_layer=1)
5. Layer 2 sentinel - single token (buffer catches [[NOT_FOUND]], aborts stream, fallback_layer=2)
6. Layer 2 sentinel - split across stream chunks (catches [[, NOT_, FOUND]] split, aborts, fallback_layer=2)
7. Layer 3 retract - no citations (streams ungrounded text, retracts with FALLBACK_MESSAGE, fallback_layer=3)
8. Layer 3 hallucinated citation pruning (answer has [C1] and fake [C99]; [C99] dropped, [C1] emitted)
9. Router JSON parse failure fails open to SEARCH with raw message
10. Redis down allows chat stream to complete cleanly without memory
11. LLM streaming error yields error event with system error message and done
12. Audit query_logs row is persisted with all telemetry fields
"""
import json
import uuid
import pytest
from typing import List, Tuple, AsyncIterator
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.core.security import create_access_token
from app.db.session import AsyncSessionLocal
from app.models.sql_models import QueryLog
from app.services.rag_engine import RetrievedChunk, RetrievalResult
from app.services.llm.base import LLMAdapter, LLMUnavailableError
from app.services.session_manager import get_session_manager


def parse_sse_events(response_text: str) -> List[Tuple[str, dict]]:
    """Parse raw HTTP SSE text into a list of (event_name, data_dict) tuples."""
    events = []
    blocks = response_text.strip().split("\n\n")
    for block in blocks:
        if not block.strip():
            continue
        lines = block.strip().split("\n")
        event_name = None
        data = None
        for line in lines:
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_str = line.split(":", 1)[1].strip()
                data = json.loads(data_str)
        if event_name:
            events.append((event_name, data))
    return events


def get_auth_headers(client: TestClient) -> Tuple[dict, str]:
    """Register a fresh user and issue JWT directly to avoid login endpoint rate limits."""
    email = f"rag_user_{uuid.uuid4().hex[:8]}@example.com"
    pwd = "TestPassword123!"
    r = client.post("/api/v1/auth/register", json={"email": email, "password": pwd})
    assert r.status_code == 201
    user_id = str(r.json()["id"])
    token = create_access_token(user_id=user_id, role="user")
    return {"Authorization": f"Bearer {token}"}, user_id


class FakeStreamAdapter(LLMAdapter):
    """Configurable mock LLM adapter for testing completion and streaming behaviors."""
    def __init__(self, complete_text: str = "{}", stream_chunks: List[str] = None, stream_exc: Exception = None):
        self.complete_text = complete_text
        self.stream_chunks = stream_chunks or ["This is an answer [C1]."]
        self.stream_exc = stream_exc

    async def complete(self, system: str, messages: list, model: str = None, max_tokens: int = None, temperature: float = None) -> str:
        return self.complete_text

    async def stream(self, system: str, messages: list, model: str = None, max_tokens: int = None, temperature: float = None) -> AsyncIterator[str]:
        if self.stream_exc:
            raise self.stream_exc
        for chunk in self.stream_chunks:
            yield chunk


def sample_retrieved_chunks(count: int = 1) -> List[RetrievedChunk]:
    chunks = []
    for i in range(1, count + 1):
        chunks.append(
            RetrievedChunk(
                chunk_id=f"chunk-uuid-{i}",
                document_id=f"doc-uuid-{i}",
                version=1,
                chunk_index=i - 1,
                content=f"Knowledge excerpt number {i} regarding crypto algorithms.",
                page_number=i,
                section_heading="Cryptographic Basics",
                document_name=f"Lecture_{i}.pdf",
                retrieval_score=0.85,
                rerank_score=0.92,
                raw_rerank_score=2.45,
            )
        )
    return chunks


# ==============================================================================
# Pipeline Branch Tests
# ==============================================================================

def test_pipeline_pure_greeting(client: TestClient, monkeypatch):
    """Verify pure greeting returns canned GREETING_MESSAGE and terminates without search."""
    headers, _ = get_auth_headers(client)

    router_adapter = FakeStreamAdapter(
        complete_text=json.dumps({"intent": "GREETING", "clarification_message": None, "standalone_query": None})
    )
    monkeypatch.setattr(
        "app.services.intent_router.get_llm_adapter",
        lambda role="router": (router_adapter, "mock-router-model"),
    )

    resp = client.post(
        "/api/v1/chat/stream",
        headers=headers,
        json={"session_id": "test-sess-greet", "message": "hello there"},
    )
    assert resp.status_code == 200
    events = parse_sse_events(resp.text)

    assert len(events) == 2
    assert events[0][0] == "token"
    assert events[0][1]["text"] == settings.GREETING_MESSAGE
    assert events[1][0] == "done"
    assert events[1][1]["intent"] == "GREETING"
    assert events[1][1]["fallback_layer"] is None


def test_pipeline_clarification(client: TestClient, monkeypatch):
    """Verify ambiguous input returns clarification message and terminates without search."""
    headers, _ = get_auth_headers(client)

    clarify_msg = "Could you specify which cryptographic hash function you mean?"
    router_adapter = FakeStreamAdapter(
        complete_text=json.dumps({"intent": "CLARIFY", "clarification_message": clarify_msg, "standalone_query": None})
    )
    monkeypatch.setattr(
        "app.services.intent_router.get_llm_adapter",
        lambda role="router": (router_adapter, "mock-router-model"),
    )

    resp = client.post(
        "/api/v1/chat/stream",
        headers=headers,
        json={"session_id": "test-sess-clarify", "message": "how does it work?"},
    )
    assert resp.status_code == 200
    events = parse_sse_events(resp.text)

    assert len(events) == 2
    assert events[0][0] == "token"
    assert events[0][1]["text"] == clarify_msg
    assert events[1][0] == "done"
    assert events[1][1]["intent"] == "CLARIFY"
    assert events[1][1]["fallback_layer"] is None


@pytest.mark.asyncio
async def test_pipeline_followup_rewrite_and_successful_answer(client: TestClient, monkeypatch):
    """Verify pronoun query is rewritten using history, searches, streams tokens, and emits citations."""
    headers, user_id = get_auth_headers(client)
    session_id = f"test-sess-rewrite-{uuid.uuid4().hex[:6]}"

    # Pre-populate session with history
    sm = get_session_manager()
    await sm.append_message(user_id, session_id, "user", "What is SHA-256?")
    await sm.append_message(user_id, session_id, "assistant", "SHA-256 is a 256-bit cryptographic hash function.")

    # Router rewrites "What is its output size?" -> "What is the output size of SHA-256?"
    router_adapter = FakeStreamAdapter(
        complete_text=json.dumps({
            "intent": "SEARCH",
            "clarification_message": None,
            "standalone_query": "What is the output size of SHA-256?",
        })
    )
    answer_adapter = FakeStreamAdapter(
        stream_chunks=["The output size ", "is 256 bits ", "[C1]."]
    )

    def mock_get_adapter(role="answer"):
        if role in ("fast", "router"):
            return router_adapter, "mock-router-model"
        return answer_adapter, "mock-answer-model"

    monkeypatch.setattr("app.services.intent_router.get_llm_adapter", mock_get_adapter)
    monkeypatch.setattr("app.api.v1.chat.get_llm_adapter", mock_get_adapter)

    # Mock RAG engine
    mock_chunks = sample_retrieved_chunks(1)
    mock_retrieval = RetrievalResult(
        query="What is the output size of SHA-256?",
        chunks=mock_chunks,
        top_score=0.95,
        raw_top_score=2.9,
        is_fallback=False,
    )
    monkeypatch.setattr("app.api.v1.chat.RAGEngine.retrieve", lambda self, query: mock_retrieval)

    resp = client.post(
        "/api/v1/chat/stream",
        headers=headers,
        json={"session_id": session_id, "message": "What is its output size?"},
    )
    assert resp.status_code == 200
    events = parse_sse_events(resp.text)

    # Tokens streamed
    token_events = [e for e in events if e[0] == "token"]
    assert len(token_events) >= 1
    full_text = "".join(e[1]["text"] for e in token_events)
    assert "The output size is 256 bits [C1]." == full_text

    # Citations emitted
    citation_events = [e for e in events if e[0] == "citations"]
    assert len(citation_events) == 1
    cites = citation_events[0][1]["citations"]
    assert len(cites) == 1
    assert cites[0]["tag"] == "C1"
    assert cites[0]["chunk_id"] == "chunk-uuid-1"

    # Done emitted
    done_events = [e for e in events if e[0] == "done"]
    assert len(done_events) == 1
    assert done_events[0][1]["intent"] == "SEARCH"
    assert done_events[0][1]["fallback_layer"] is None


def test_pipeline_layer1_fallback(client: TestClient, monkeypatch):
    """Verify low reranker score triggers Layer 1 fallback before generation."""
    headers, _ = get_auth_headers(client)

    router_adapter = FakeStreamAdapter(
        complete_text=json.dumps({"intent": "SEARCH", "clarification_message": None, "standalone_query": "beef bourguignon recipe"})
    )
    monkeypatch.setattr(
        "app.services.intent_router.get_llm_adapter",
        lambda role="router": (router_adapter, "mock-router-model"),
    )

    mock_retrieval = RetrievalResult(
        query="beef bourguignon recipe",
        chunks=[],
        top_score=0.001,
        raw_top_score=-6.9,
        is_fallback=True,
        fallback_message=settings.FALLBACK_MESSAGE,
    )
    monkeypatch.setattr("app.api.v1.chat.RAGEngine.retrieve", lambda self, query: mock_retrieval)

    resp = client.post(
        "/api/v1/chat/stream",
        headers=headers,
        json={"session_id": "test-sess-l1", "message": "how to cook beef bourguignon?"},
    )
    assert resp.status_code == 200
    events = parse_sse_events(resp.text)

    assert len(events) == 2
    assert events[0][0] == "token"
    assert events[0][1]["text"] == settings.FALLBACK_MESSAGE
    assert events[1][0] == "done"
    assert events[1][1]["intent"] == "SEARCH"
    assert events[1][1]["fallback_layer"] == 1


def test_pipeline_layer2_sentinel_single_chunk(client: TestClient, monkeypatch):
    """Verify single-chunk [[NOT_FOUND]] sentinel aborts stream and triggers Layer 2 fallback."""
    headers, _ = get_auth_headers(client)

    router_adapter = FakeStreamAdapter(
        complete_text=json.dumps({"intent": "SEARCH", "clarification_message": None, "standalone_query": "quantum crypto"})
    )
    answer_adapter = FakeStreamAdapter(stream_chunks=["[[NOT_FOUND]]"])

    def mock_get_adapter(role="answer"):
        if role in ("fast", "router"):
            return router_adapter, "mock-router-model"
        return answer_adapter, "mock-answer-model"

    monkeypatch.setattr("app.services.intent_router.get_llm_adapter", mock_get_adapter)
    monkeypatch.setattr("app.api.v1.chat.get_llm_adapter", mock_get_adapter)

    mock_chunks = sample_retrieved_chunks(1)
    mock_retrieval = RetrievalResult(
        query="quantum crypto",
        chunks=mock_chunks,
        top_score=0.88,
        is_fallback=False,
    )
    monkeypatch.setattr("app.api.v1.chat.RAGEngine.retrieve", lambda self, query: mock_retrieval)

    resp = client.post(
        "/api/v1/chat/stream",
        headers=headers,
        json={"session_id": "test-sess-l2-single", "message": "tell me about quantum crypto"},
    )
    assert resp.status_code == 200
    events = parse_sse_events(resp.text)

    # Sentinel must NOT leak to client as text; user receives FALLBACK_MESSAGE
    token_events = [e for e in events if e[0] == "token"]
    assert len(token_events) == 1
    assert token_events[0][1]["text"] == settings.FALLBACK_MESSAGE

    done_events = [e for e in events if e[0] == "done"]
    assert len(done_events) == 1
    assert done_events[0][1]["fallback_layer"] == 2


def test_pipeline_layer2_sentinel_split_across_chunks(client: TestClient, monkeypatch):
    """Verify [[NOT_FOUND]] sentinel split across 3 tokens is caught by buffer without leaking."""
    headers, _ = get_auth_headers(client)

    router_adapter = FakeStreamAdapter(
        complete_text=json.dumps({"intent": "SEARCH", "clarification_message": None, "standalone_query": "zero knowledge proof details"})
    )
    # Split across token boundaries
    answer_adapter = FakeStreamAdapter(stream_chunks=["[[", "NOT_", "FOUND]]"])

    def mock_get_adapter(role="answer"):
        if role in ("fast", "router"):
            return router_adapter, "mock-router-model"
        return answer_adapter, "mock-answer-model"

    monkeypatch.setattr("app.services.intent_router.get_llm_adapter", mock_get_adapter)
    monkeypatch.setattr("app.api.v1.chat.get_llm_adapter", mock_get_adapter)

    mock_chunks = sample_retrieved_chunks(1)
    mock_retrieval = RetrievalResult(
        query="zero knowledge proof details",
        chunks=mock_chunks,
        top_score=0.89,
        is_fallback=False,
    )
    monkeypatch.setattr("app.api.v1.chat.RAGEngine.retrieve", lambda self, query: mock_retrieval)

    resp = client.post(
        "/api/v1/chat/stream",
        headers=headers,
        json={"session_id": "test-sess-l2-split", "message": "what is zk proof?"},
    )
    assert resp.status_code == 200
    events = parse_sse_events(resp.text)

    token_events = [e for e in events if e[0] == "token"]
    assert len(token_events) == 1
    assert token_events[0][1]["text"] == settings.FALLBACK_MESSAGE

    done_events = [e for e in events if e[0] == "done"]
    assert len(done_events) == 1
    assert done_events[0][1]["fallback_layer"] == 2


def test_pipeline_layer3_retract_on_ungrounded_answer(client: TestClient, monkeypatch):
    """Verify that an answer streamed without valid citations emits a retract event (Layer 3)."""
    headers, _ = get_auth_headers(client)

    router_adapter = FakeStreamAdapter(
        complete_text=json.dumps({"intent": "SEARCH", "clarification_message": None, "standalone_query": "hash algorithm history"})
    )
    # Model generates answer but completely fails to include any [C1] citation
    answer_adapter = FakeStreamAdapter(stream_chunks=["Here is a completely ungrounded answer without citations."])

    def mock_get_adapter(role="answer"):
        if role in ("fast", "router"):
            return router_adapter, "mock-router-model"
        return answer_adapter, "mock-answer-model"

    monkeypatch.setattr("app.services.intent_router.get_llm_adapter", mock_get_adapter)
    monkeypatch.setattr("app.api.v1.chat.get_llm_adapter", mock_get_adapter)

    mock_chunks = sample_retrieved_chunks(1)
    mock_retrieval = RetrievalResult(
        query="hash algorithm history",
        chunks=mock_chunks,
        top_score=0.91,
        is_fallback=False,
    )
    monkeypatch.setattr("app.api.v1.chat.RAGEngine.retrieve", lambda self, query: mock_retrieval)

    resp = client.post(
        "/api/v1/chat/stream",
        headers=headers,
        json={"session_id": "test-sess-l3-retract", "message": "tell me history"},
    )
    assert resp.status_code == 200
    events = parse_sse_events(resp.text)

    # Client saw initial tokens
    token_events = [e for e in events if e[0] == "token"]
    assert len(token_events) > 0

    # Retract event was sent
    retract_events = [e for e in events if e[0] == "retract"]
    assert len(retract_events) == 1
    assert retract_events[0][1]["text"] == settings.FALLBACK_MESSAGE

    # Done has fallback_layer=3
    done_events = [e for e in events if e[0] == "done"]
    assert len(done_events) == 1
    assert done_events[0][1]["fallback_layer"] == 3


def test_pipeline_layer3_hallucinated_citation_pruned(client: TestClient, monkeypatch):
    """Verify hallucinated tag [C99] is dropped while valid [C1] is retained and emitted."""
    headers, _ = get_auth_headers(client)

    router_adapter = FakeStreamAdapter(
        complete_text=json.dumps({"intent": "SEARCH", "clarification_message": None, "standalone_query": "hash collision"})
    )
    # Model cites valid [C1] and fake [C99] when only 1 chunk was in context
    answer_adapter = FakeStreamAdapter(stream_chunks=["Collision resistance is discussed in [C1] and also in [C99]."])

    def mock_get_adapter(role="answer"):
        if role in ("fast", "router"):
            return router_adapter, "mock-router-model"
        return answer_adapter, "mock-answer-model"

    monkeypatch.setattr("app.services.intent_router.get_llm_adapter", mock_get_adapter)
    monkeypatch.setattr("app.api.v1.chat.get_llm_adapter", mock_get_adapter)

    mock_chunks = sample_retrieved_chunks(1)
    mock_retrieval = RetrievalResult(
        query="hash collision",
        chunks=mock_chunks,
        top_score=0.93,
        is_fallback=False,
    )
    monkeypatch.setattr("app.api.v1.chat.RAGEngine.retrieve", lambda self, query: mock_retrieval)

    resp = client.post(
        "/api/v1/chat/stream",
        headers=headers,
        json={"session_id": "test-sess-l3-prune", "message": "collision resistance"},
    )
    assert resp.status_code == 200
    events = parse_sse_events(resp.text)

    # Must NOT have retracted
    assert not any(e[0] == "retract" for e in events)

    # Citations event must include ONLY C1, NOT C99
    citation_events = [e for e in events if e[0] == "citations"]
    assert len(citation_events) == 1
    cites = citation_events[0][1]["citations"]
    assert len(cites) == 1
    assert cites[0]["tag"] == "C1"

    done_events = [e for e in events if e[0] == "done"]
    assert done_events[0][1]["fallback_layer"] is None


def test_pipeline_router_json_failure_fails_open_to_search(client: TestClient, monkeypatch):
    """Verify persistent invalid JSON from router fails open to SEARCH with raw message."""
    headers, _ = get_auth_headers(client)

    router_adapter = FakeStreamAdapter(complete_text="Not valid json at all")
    answer_adapter = FakeStreamAdapter(stream_chunks=["Answer to raw query [C1]."])

    def mock_get_adapter(role="answer"):
        if role in ("fast", "router"):
            return router_adapter, "mock-router-model"
        return answer_adapter, "mock-answer-model"

    monkeypatch.setattr("app.services.intent_router.get_llm_adapter", mock_get_adapter)
    monkeypatch.setattr("app.api.v1.chat.get_llm_adapter", mock_get_adapter)

    mock_chunks = sample_retrieved_chunks(1)
    captured_query = None

    def mock_retrieve(self, query):
        nonlocal captured_query
        captured_query = query
        return RetrievalResult(
            query=query,
            chunks=mock_chunks,
            top_score=0.92,
            is_fallback=False,
        )

    monkeypatch.setattr("app.api.v1.chat.RAGEngine.retrieve", mock_retrieve)

    resp = client.post(
        "/api/v1/chat/stream",
        headers=headers,
        json={"session_id": "test-sess-fail-open", "message": "What is Merkle tree?"},
    )
    assert resp.status_code == 200
    events = parse_sse_events(resp.text)

    # Retrieval was executed using raw user message
    assert captured_query == "What is Merkle tree?"
    done_events = [e for e in events if e[0] == "done"]
    assert done_events[0][1]["intent"] == "SEARCH"


def test_pipeline_redis_down_resilience(client: TestClient, monkeypatch):
    """Verify chat streaming succeeds gracefully even when Redis is down."""
    headers, _ = get_auth_headers(client)

    router_adapter = FakeStreamAdapter(
        complete_text=json.dumps({"intent": "SEARCH", "clarification_message": None, "standalone_query": "redis down test"})
    )
    answer_adapter = FakeStreamAdapter(stream_chunks=["Answer when redis is down [C1]."])

    def mock_get_adapter(role="answer"):
        if role in ("fast", "router"):
            return router_adapter, "mock-router-model"
        return answer_adapter, "mock-answer-model"

    monkeypatch.setattr("app.services.intent_router.get_llm_adapter", mock_get_adapter)
    monkeypatch.setattr("app.api.v1.chat.get_llm_adapter", mock_get_adapter)

    mock_chunks = sample_retrieved_chunks(1)
    mock_retrieval = RetrievalResult(
        query="redis down test",
        chunks=mock_chunks,
        top_score=0.91,
        is_fallback=False,
    )
    monkeypatch.setattr("app.api.v1.chat.RAGEngine.retrieve", lambda self, query: mock_retrieval)

    # Simulate broken Redis in SessionManager
    class BrokenRedis:
        async def lrange(self, *args, **kwargs):
            raise ConnectionError("Redis down")
        async def rpush(self, *args, **kwargs):
            raise ConnectionError("Redis down")
        async def ltrim(self, *args, **kwargs):
            raise ConnectionError("Redis down")
        async def expire(self, *args, **kwargs):
            raise ConnectionError("Redis down")
        async def zadd(self, *args, **kwargs):
            raise ConnectionError("Redis down")

    monkeypatch.setattr("app.api.v1.chat.get_session_manager", lambda: get_session_manager(client=BrokenRedis()))

    resp = client.post(
        "/api/v1/chat/stream",
        headers=headers,
        json={"session_id": "test-sess-redis-down", "message": "test query"},
    )
    assert resp.status_code == 200
    events = parse_sse_events(resp.text)

    done_events = [e for e in events if e[0] == "done"]
    assert len(done_events) == 1
    assert done_events[0][1]["intent"] == "SEARCH"


def test_pipeline_llm_stream_error(client: TestClient, monkeypatch):
    """Verify LLM error during generation yields structured error event with system error message."""
    headers, _ = get_auth_headers(client)

    router_adapter = FakeStreamAdapter(
        complete_text=json.dumps({"intent": "SEARCH", "clarification_message": None, "standalone_query": "llm error test"})
    )
    # Answer stream raises LLMUnavailableError
    answer_adapter = FakeStreamAdapter(stream_exc=LLMUnavailableError("503 Service Unavailable"))

    def mock_get_adapter(role="answer"):
        if role in ("fast", "router"):
            return router_adapter, "mock-router-model"
        return answer_adapter, "mock-answer-model"

    monkeypatch.setattr("app.services.intent_router.get_llm_adapter", mock_get_adapter)
    monkeypatch.setattr("app.api.v1.chat.get_llm_adapter", mock_get_adapter)

    mock_chunks = sample_retrieved_chunks(1)
    mock_retrieval = RetrievalResult(
        query="llm error test",
        chunks=mock_chunks,
        top_score=0.91,
        is_fallback=False,
    )
    monkeypatch.setattr("app.api.v1.chat.RAGEngine.retrieve", lambda self, query: mock_retrieval)

    resp = client.post(
        "/api/v1/chat/stream",
        headers=headers,
        json={"session_id": "test-sess-llm-error", "message": "test query"},
    )
    assert resp.status_code == 200
    events = parse_sse_events(resp.text)

    error_events = [e for e in events if e[0] == "error"]
    assert len(error_events) == 1
    assert error_events[0][1]["message"] == settings.SYSTEM_ERROR_MESSAGE
    assert error_events[0][1]["code"] == "LLM_UNAVAILABLE"

    done_events = [e for e in events if e[0] == "done"]
    assert len(done_events) == 1


@pytest.mark.asyncio
async def test_pipeline_query_logs_persisted(client: TestClient, monkeypatch):
    """Verify that query execution writes an audit row to query_logs with latencies, scores, and chunk IDs."""
    headers, user_id = get_auth_headers(client)
    unique_sess = f"sess-log-{uuid.uuid4().hex[:8]}"

    router_adapter = FakeStreamAdapter(
        complete_text=json.dumps({"intent": "SEARCH", "clarification_message": None, "standalone_query": "query log test"})
    )
    answer_adapter = FakeStreamAdapter(stream_chunks=["Answer logged [C1]."])

    def mock_get_adapter(role="answer"):
        if role in ("fast", "router"):
            return router_adapter, "mock-router-model"
        return answer_adapter, "mock-answer-model"

    monkeypatch.setattr("app.services.intent_router.get_llm_adapter", mock_get_adapter)
    monkeypatch.setattr("app.api.v1.chat.get_llm_adapter", mock_get_adapter)

    mock_chunks = sample_retrieved_chunks(1)
    mock_retrieval = RetrievalResult(
        query="query log test",
        chunks=mock_chunks,
        top_score=0.94,
        is_fallback=False,
    )
    monkeypatch.setattr("app.api.v1.chat.RAGEngine.retrieve", lambda self, query: mock_retrieval)

    resp = client.post(
        "/api/v1/chat/stream",
        headers=headers,
        json={"session_id": unique_sess, "message": "query log test message"},
    )
    assert resp.status_code == 200

    # Query query_logs table to verify telemetry persistence
    async with AsyncSessionLocal() as db_session:
        stmt = select(QueryLog).where(QueryLog.session_id == unique_sess)
        result = await db_session.execute(stmt)
        log_rows = result.scalars().all()
        assert len(log_rows) == 1
        row = log_rows[0]
        assert str(row.user_id) == user_id
        assert row.intent == "SEARCH"
        assert row.original_query == "query log test message"
        assert row.standalone_query == "query log test"
        assert row.top_score == 0.94
        assert row.fallback_layer is None
        assert row.cited_chunk_ids == ["chunk-uuid-1"]
        assert row.latency_ms_router is not None
        assert row.latency_ms_generation is not None
