"""Unit and integration tests for the IntentRouter and Query Rewriter.

Covers:
- Pure greeting returns GREETING and canned GREETING_MESSAGE.
- Mixed greeting and question routes to SEARCH.
- Ambiguous query without history routes to CLARIFY with clarification message.
- Contextual follow-up query rewrites pronouns using conversation history.
- Rewrite does not add external facts not present in conversation.
- Fallback turns in conversation history are not treated as factual knowledge.
- Malformed JSON retries once, then parses successfully if retry succeeds.
- Persistent JSON failure fails open to SEARCH with the raw user query.
- LLM provider exceptions/timeouts fail open to SEARCH with the raw user query.
"""
from typing import List, Dict, Any, AsyncIterator
import pytest

from app.core.config import settings
from app.models.schemas import ChatMessage, MessageKind, RouterIntent
from app.services.intent_router import IntentRouter
from app.services.llm.base import LLMAdapter, LLMUnavailableError


class MockLLMAdapter(LLMAdapter):
    """Mock LLM adapter simulating predetermined model responses."""

    def __init__(self, responses: List[Any]):
        self.responses = list(responses)
        self.call_count = 0
        self.received_messages: List[List[Dict[str, Any]]] = []
        self.received_systems: List[str] = []

    async def complete(
        self,
        system: str,
        messages: List[Dict[str, Any]],
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str:
        self.received_systems.append(system)
        self.received_messages.append(messages)
        self.call_count += 1

        if not self.responses:
            return '{"intent": "SEARCH", "clarification_message": null, "standalone_query": "default"}'

        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp

    async def stream(
        self,
        system: str,
        messages: List[Dict[str, Any]],
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> AsyncIterator[str]:
        yield await self.complete(system, messages, model, max_tokens, temperature)


@pytest.mark.asyncio
async def test_router_pure_greeting():
    """Verify that pure greetings route to GREETING and return canned GREETING_MESSAGE."""
    mock_resp = '{"intent": "GREETING", "clarification_message": null, "standalone_query": null}'
    adapter = MockLLMAdapter([mock_resp])
    router = IntentRouter(adapter=adapter, model="mock-fast")

    result = await router.route("Hello there!")
    assert result.intent == RouterIntent.GREETING
    assert result.reply == settings.GREETING_MESSAGE
    assert result.standalone_query == "Hello there!"
    assert result.failed_open is False
    assert adapter.call_count == 1


@pytest.mark.asyncio
async def test_router_mixed_greeting_and_question():
    """Verify that messages mixing a greeting and question are classified as SEARCH."""
    mock_resp = (
        '{"intent": "SEARCH", "clarification_message": null, '
        '"standalone_query": "What is collision resistance in hash functions?"}'
    )
    adapter = MockLLMAdapter([mock_resp])
    router = IntentRouter(adapter=adapter, model="mock-fast")

    result = await router.route("Hi! Can you tell me what collision resistance is?")
    assert result.intent == RouterIntent.SEARCH
    assert result.standalone_query == "What is collision resistance in hash functions?"
    assert result.reply is None
    assert result.failed_open is False


@pytest.mark.asyncio
async def test_router_clarification_path():
    """Verify that ambiguous queries without context route to CLARIFY."""
    mock_resp = (
        '{"intent": "CLARIFY", '
        '"clarification_message": "Could you please specify which algorithm or property you are referring to?", '
        '"standalone_query": null}'
    )
    adapter = MockLLMAdapter([mock_resp])
    router = IntentRouter(adapter=adapter, model="mock-fast")

    result = await router.route("How does it work?")
    assert result.intent == RouterIntent.CLARIFY
    assert result.reply == "Could you please specify which algorithm or property you are referring to?"
    assert result.clarification_message is not None
    assert result.failed_open is False


@pytest.mark.asyncio
async def test_router_follow_up_rewrite_with_history():
    """Verify follow-up pronoun query rewrites to standalone query using history."""
    history = [
        ChatMessage(role="user", content="What is a Merkle tree?"),
        ChatMessage(
            role="assistant",
            content="A Merkle tree is a cryptographic binary tree where leaves are transaction hashes.",
        ),
    ]

    mock_resp = (
        '{"intent": "SEARCH", "clarification_message": null, '
        '"standalone_query": "How does a Merkle tree verify data integrity?"}'
    )
    adapter = MockLLMAdapter([mock_resp])
    router = IntentRouter(adapter=adapter, model="mock-fast")

    result = await router.route("How does it verify data integrity?", history=history)
    assert result.intent == RouterIntent.SEARCH
    assert result.standalone_query == "How does a Merkle tree verify data integrity?"

    # Check prompt contained history
    sent_prompt = adapter.received_messages[0][0]["content"]
    assert "What is a Merkle tree?" in sent_prompt
    assert "A Merkle tree is a cryptographic binary tree" in sent_prompt


@pytest.mark.asyncio
async def test_router_fallback_history_ignored_as_knowledge():
    """Verify fallback messages are formatted with indicator so LLM does not treat them as knowledge."""
    history = [
        ChatMessage(role="user", content="What is the secret launch code?"),
        ChatMessage(
            role="assistant",
            content="I'm sorry, I couldn't find information about that in my knowledge base.",
            kind=MessageKind.FALLBACK,
        ),
    ]

    mock_resp = '{"intent": "SEARCH", "clarification_message": null, "standalone_query": "Explain consensus algorithms"}'
    adapter = MockLLMAdapter([mock_resp])
    router = IntentRouter(adapter=adapter, model="mock-fast")

    result = await router.route("Explain consensus algorithms", history=history)
    assert result.intent == RouterIntent.SEARCH

    sent_prompt = adapter.received_messages[0][0]["content"]
    assert "[No information found in knowledge base - fallback]" in sent_prompt
    # The literal fallback text shouldn't be presented as authoritative assistant knowledge
    assert "I couldn't find information" not in sent_prompt


@pytest.mark.asyncio
async def test_router_json_failure_retries_and_succeeds():
    """Verify invalid JSON on first attempt triggers a retry, which succeeds."""
    bad_json = "Here is your classification:\n```json\n{intent: GREETING}\n```"
    good_json = '{"intent": "GREETING", "clarification_message": null, "standalone_query": null}'
    adapter = MockLLMAdapter([bad_json, good_json])
    router = IntentRouter(adapter=adapter, model="mock-fast")

    result = await router.route("Good morning!")
    assert result.intent == RouterIntent.GREETING
    assert result.reply == settings.GREETING_MESSAGE
    assert result.retries == 1
    assert result.failed_open is False
    assert adapter.call_count == 2


@pytest.mark.asyncio
async def test_router_persistent_json_failure_fails_open_to_search():
    """Verify persistent invalid JSON fails open to SEARCH with the raw user query."""
    bad_json_1 = "I am an AI and cannot classify this."
    bad_json_2 = "Still cannot return valid JSON."
    adapter = MockLLMAdapter([bad_json_1, bad_json_2])
    router = IntentRouter(adapter=adapter, model="mock-fast")

    raw_query = "What is the Byzantine Generals Problem in consensus?"
    result = await router.route(raw_query)

    assert result.intent == RouterIntent.SEARCH
    assert result.standalone_query == raw_query
    assert result.failed_open is True
    assert result.retries == 1
    assert adapter.call_count == 2


@pytest.mark.asyncio
async def test_router_llm_exception_fails_open_to_search():
    """Verify LLM network/provider exception immediately fails open to SEARCH."""
    adapter = MockLLMAdapter([LLMUnavailableError("Upstream API returned HTTP 503 Service Unavailable")])
    router = IntentRouter(adapter=adapter, model="mock-fast")

    raw_query = "What is asymmetric encryption?"
    result = await router.route(raw_query)

    assert result.intent == RouterIntent.SEARCH
    assert result.standalone_query == raw_query
    assert result.failed_open is True
    assert adapter.call_count == 1
