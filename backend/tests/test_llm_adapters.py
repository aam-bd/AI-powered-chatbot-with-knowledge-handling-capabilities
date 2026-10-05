"""Unit tests for LLM provider adapters, base validation, error mapping, and factory.

Acceptance criteria from Prompt 1.5:
- System prompt placement for both adapters
- Streaming token iteration
- Normalized error mapping (LLMAuthError, LLMRateLimitError, LLMTimeoutError, LLMUnavailableError)
- Retries with exponential backoff on 429 and 5xx
- Base URL validation (HTTPS required, localhost/private IPs allowed, trailing slashes normalized)
- API key masking so credentials never leak in logs or exception messages
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import openai
import anthropic
from pydantic import SecretStr

from app.services.llm.base import (
    LLMAdapter,
    LLMError,
    LLMAuthError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    validate_base_url,
    mask_api_key,
)
from app.services.llm.openai_compat import OpenAICompatAdapter
from app.services.llm.anthropic import AnthropicAdapter
from app.services.llm.factory import get_llm_adapter
from app.core.config import settings


# ------------------------------------------------------------------------------
# 1. Base URL Validation & Key Masking Tests
# ------------------------------------------------------------------------------

def test_base_url_validation():
    # Valid remote HTTPS
    assert validate_base_url("https://api.openai.com/v1/") == "https://api.openai.com/v1"
    assert validate_base_url("https://generativelanguage.googleapis.com/v1beta/openai/") == "https://generativelanguage.googleapis.com/v1beta/openai"

    # Valid local / private HTTP
    assert validate_base_url("http://localhost:11434/v1") == "http://localhost:11434/v1"
    assert validate_base_url("http://127.0.0.1:8000/v1/") == "http://127.0.0.1:8000/v1"
    assert validate_base_url("http://192.168.1.100:8080/v1") == "http://192.168.1.100:8080/v1"
    assert validate_base_url("http://10.0.0.5:8000/v1") == "http://10.0.0.5:8000/v1"

    # Insecure remote HTTP must fail
    with pytest.raises(ValueError, match="HTTPS is strictly required"):
        validate_base_url("http://api.remote-llm.com/v1")

    # Invalid scheme
    with pytest.raises(ValueError, match="Invalid URL scheme"):
        validate_base_url("ftp://api.remote-llm.com/v1")

    # Empty URL
    with pytest.raises(ValueError):
        validate_base_url("")


def test_mask_api_key():
    assert mask_api_key("") == ""
    assert mask_api_key("12345") == "***"
    assert mask_api_key("sk-1234567890abcdef") == "sk-1...cdef"
    assert mask_api_key("AIzaSyDummyFakeGoogleStudioKey1234567890") == "AIza...7890"


# ------------------------------------------------------------------------------
# 2. System Prompt Placement Tests
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_openai_compat_system_prompt_placement():
    adapter = OpenAICompatAdapter(
        api_key="test-key-12345678",
        base_url="https://api.openai.com/v1",
        timeout=10.0,
        max_retries=1,
    )

    mock_choice = MagicMock()
    mock_choice.message.content = "Response from model"
    mock_response = MagicMock(choices=[mock_choice])

    adapter.client.chat.completions.create = AsyncMock(return_value=mock_response)

    res = await adapter.complete(
        system="You are a helpful assistant.",
        messages=[{"role": "user", "content": "Hello"}],
        model="gpt-4o",
    )

    assert res == "Response from model"
    adapter.client.chat.completions.create.assert_called_once()
    call_kwargs = adapter.client.chat.completions.create.call_args.kwargs

    # Ensure system prompt is prepended into the messages list
    expected_messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello"},
    ]
    assert call_kwargs["messages"] == expected_messages
    assert call_kwargs["model"] == "gpt-4o"


@pytest.mark.asyncio
async def test_anthropic_system_prompt_placement():
    adapter = AnthropicAdapter(
        api_key="test-key-12345678",
        base_url="https://api.anthropic.com",
        timeout=10.0,
        max_retries=1,
    )

    mock_block = MagicMock()
    mock_block.text = "Response from Claude"
    mock_response = MagicMock(content=[mock_block])

    adapter.client.messages.create = AsyncMock(return_value=mock_response)

    res = await adapter.complete(
        system="You are Claude.",
        messages=[{"role": "user", "content": "Hello"}],
        model="claude-3-5-sonnet-20241022",
    )

    assert res == "Response from Claude"
    adapter.client.messages.create.assert_called_once()
    call_kwargs = adapter.client.messages.create.call_args.kwargs

    # Ensure system prompt is in top-level system parameter, NOT inside messages
    assert call_kwargs["system"] == "You are Claude."
    assert call_kwargs["messages"] == [{"role": "user", "content": "Hello"}]
    assert call_kwargs["model"] == "claude-3-5-sonnet-20241022"


# ------------------------------------------------------------------------------
# 3. Streaming Tests
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_openai_compat_streaming():
    adapter = OpenAICompatAdapter(
        api_key="test-key-12345678",
        base_url="https://api.openai.com/v1",
    )

    # Mock chunk generator
    async def mock_stream_chunks():
        for token in ["Hello", " ", "world", "!"]:
            chunk = MagicMock()
            delta = MagicMock()
            delta.content = token
            choice = MagicMock(delta=delta)
            chunk.choices = [choice]
            yield chunk

    adapter.client.chat.completions.create = AsyncMock(return_value=mock_stream_chunks())

    tokens = []
    async for token in adapter.stream(
        system="Sys", messages=[{"role": "user", "content": "Hi"}], model="gpt-4o"
    ):
        tokens.append(token)

    assert "".join(tokens) == "Hello world!"


@pytest.mark.asyncio
async def test_anthropic_streaming():
    adapter = AnthropicAdapter(
        api_key="test-key-12345678",
    )

    class MockStreamContext:
        async def __aenter__(self):
            stream_obj = MagicMock()
            async def text_gen():
                for tok in ["Hello", " ", "Claude", "!"]:
                    yield tok
            stream_obj.text_stream = text_gen()
            return stream_obj

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    adapter.client.messages.stream = MagicMock(return_value=MockStreamContext())

    tokens = []
    async for token in adapter.stream(
        system="Sys", messages=[{"role": "user", "content": "Hi"}], model="claude-3-5-haiku"
    ):
        tokens.append(token)

    assert "".join(tokens) == "Hello Claude!"


# ------------------------------------------------------------------------------
# 4. Error Mapping Tests
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_openai_error_mapping():
    adapter = OpenAICompatAdapter(api_key="test-key", base_url="https://api.openai.com/v1", max_retries=0)

    # 401 Authentication
    req = MagicMock()
    adapter.client.chat.completions.create = AsyncMock(
        side_effect=openai.AuthenticationError("Invalid API key", response=MagicMock(status_code=401), body={})
    )
    with pytest.raises(LLMAuthError):
        await adapter.complete("Sys", [{"role": "user", "content": "Hi"}], "test-model")

    # 429 Rate Limit
    adapter.client.chat.completions.create = AsyncMock(
        side_effect=openai.RateLimitError("Rate limit exceeded", response=MagicMock(status_code=429), body={})
    )
    with pytest.raises(LLMRateLimitError):
        await adapter.complete("Sys", [{"role": "user", "content": "Hi"}], "test-model")

    # Timeout
    adapter.client.chat.completions.create = AsyncMock(
        side_effect=openai.APITimeoutError(request=req)
    )
    with pytest.raises(LLMTimeoutError):
        await adapter.complete("Sys", [{"role": "user", "content": "Hi"}], "test-model")

    # 500 Internal Server Error
    adapter.client.chat.completions.create = AsyncMock(
        side_effect=openai.InternalServerError("Server error", response=MagicMock(status_code=500), body={})
    )
    with pytest.raises(LLMUnavailableError):
        await adapter.complete("Sys", [{"role": "user", "content": "Hi"}], "test-model")


@pytest.mark.asyncio
async def test_anthropic_error_mapping():
    adapter = AnthropicAdapter(api_key="test-key", max_retries=0)

    # 401 Authentication
    adapter.client.messages.create = AsyncMock(
        side_effect=anthropic.AuthenticationError("Invalid API key", response=MagicMock(status_code=401), body={})
    )
    with pytest.raises(LLMAuthError):
        await adapter.complete("Sys", [{"role": "user", "content": "Hi"}], "test-model")

    # 429 Rate Limit
    adapter.client.messages.create = AsyncMock(
        side_effect=anthropic.RateLimitError("Quota limit", response=MagicMock(status_code=429), body={})
    )
    with pytest.raises(LLMRateLimitError):
        await adapter.complete("Sys", [{"role": "user", "content": "Hi"}], "test-model")

    # Timeout
    adapter.client.messages.create = AsyncMock(
        side_effect=anthropic.APITimeoutError(request=MagicMock())
    )
    with pytest.raises(LLMTimeoutError):
        await adapter.complete("Sys", [{"role": "user", "content": "Hi"}], "test-model")

    # 500 Internal Server Error
    adapter.client.messages.create = AsyncMock(
        side_effect=anthropic.InternalServerError("Overloaded", response=MagicMock(status_code=500), body={})
    )
    with pytest.raises(LLMUnavailableError):
        await adapter.complete("Sys", [{"role": "user", "content": "Hi"}], "test-model")


# ------------------------------------------------------------------------------
# 5. Exponential Backoff Retries
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_exponential_backoff_recovery():
    adapter = OpenAICompatAdapter(api_key="test-key", base_url="https://api.openai.com/v1", max_retries=2)

    mock_choice = MagicMock()
    mock_choice.message.content = "Success on third try"
    mock_success = MagicMock(choices=[mock_choice])

    # Fail twice with 429, then succeed
    adapter.client.chat.completions.create = AsyncMock(
        side_effect=[
            openai.RateLimitError("Rate limit", response=MagicMock(status_code=429), body={}),
            openai.RateLimitError("Rate limit", response=MagicMock(status_code=429), body={}),
            mock_success,
        ]
    )

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        res = await adapter.complete("Sys", [{"role": "user", "content": "Hi"}], "test-model")

        assert res == "Success on third try"
        assert adapter.client.chat.completions.create.call_count == 3
        # Backoff: 1.0s, then 2.0s
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(1.0)
        mock_sleep.assert_any_call(2.0)


@pytest.mark.asyncio
async def test_retry_exhaustion_raises():
    adapter = OpenAICompatAdapter(api_key="test-key", base_url="https://api.openai.com/v1", max_retries=1)

    adapter.client.chat.completions.create = AsyncMock(
        side_effect=openai.RateLimitError("Rate limit", response=MagicMock(status_code=429), body={})
    )

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(LLMRateLimitError):
            await adapter.complete("Sys", [{"role": "user", "content": "Hi"}], "test-model")

        # Initial try + 1 retry = 2 calls
        assert adapter.client.chat.completions.create.call_count == 2


# ------------------------------------------------------------------------------
# 6. Credential Masking in Logs & Errors
# ------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_key_never_leaked_in_exceptions():
    secret_key = "SECRET_SUPER_SENSITIVE_API_KEY_VALUE_XYZ"
    adapter = OpenAICompatAdapter(api_key=secret_key, base_url="https://api.openai.com/v1", max_retries=0)

    adapter.client.chat.completions.create = AsyncMock(
        side_effect=openai.AuthenticationError(
            f"Invalid key provided: {secret_key}",
            response=MagicMock(status_code=401),
            body={},
        )
    )

    try:
        await adapter.complete("Sys", [{"role": "user", "content": "Hi"}], "test-model")
        pytest.fail("Expected LLMAuthError")
    except LLMAuthError as exc:
        error_msg = str(exc)
        assert secret_key not in error_msg
        assert "SECR..._XYZ" in error_msg


# ------------------------------------------------------------------------------
# 7. Factory Role Resolution Tests
# ------------------------------------------------------------------------------

def test_factory_role_resolution():
    # Test router role fallback to shared LLM settings
    with patch.object(settings, "LLM_PROVIDER", "openai_compatible"), \
         patch.object(settings, "LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"), \
         patch.object(settings, "LLM_API_KEY", SecretStr("test-shared-key-1234")), \
         patch.object(settings, "FAST_MODEL", "gemini-3.1-flash-lite"), \
         patch.object(settings, "FAST_LLM_PROVIDER", None), \
         patch.object(settings, "FAST_LLM_API_KEY", None):

        adapter, model = get_llm_adapter("router")
        assert isinstance(adapter, OpenAICompatAdapter)
        assert model == "gemini-3.1-flash-lite"
        assert adapter.base_url == "https://generativelanguage.googleapis.com/v1beta/openai"

    # Test answer role override
    with patch.object(settings, "LLM_PROVIDER", "openai_compatible"), \
         patch.object(settings, "LLM_BASE_URL", "https://api.openai.com/v1"), \
         patch.object(settings, "LLM_API_KEY", SecretStr("test-shared-key-1234")), \
         patch.object(settings, "ANSWER_MODEL", "claude-3-5-sonnet-20241022"), \
         patch.object(settings, "ANSWER_LLM_PROVIDER", "anthropic"), \
         patch.object(settings, "ANSWER_LLM_API_KEY", SecretStr("test-anthropic-key")):

        adapter, model = get_llm_adapter("answer")
        assert isinstance(adapter, AnthropicAdapter)
        assert model == "claude-3-5-sonnet-20241022"

    # Test missing credentials raises clear ValueError
    with patch.object(settings, "LLM_API_KEY", None), \
         patch.object(settings, "FAST_LLM_API_KEY", None):
        with pytest.raises(ValueError, match="LLM API key is not configured"):
            get_llm_adapter("router")

    # Test invalid role name raises ValueError
    with pytest.raises(ValueError, match="Unknown LLM role"):
        get_llm_adapter("nonexistent_role")
