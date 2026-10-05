"""Native Anthropic Messages API adapter.

Implements:
- System prompt placed directly into the top-level `system` parameter
- Exponential backoff retries on HTTP 429 and 5xx (up to LLM_MAX_RETRIES)
- Error mapping to normalized LLM exceptions
- Token streaming via AsyncIterator[str]
- Strict credential masking in logs and error messages
"""
import asyncio
from typing import AsyncIterator, List, Dict, Any, Optional
import anthropic
from loguru import logger

from app.services.llm.base import (
    LLMAdapter,
    LLMAuthError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
    validate_base_url,
    mask_api_key,
)


class AnthropicAdapter(LLMAdapter):
    """Adapter for native Anthropic Messages API."""

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = "https://api.anthropic.com",
        timeout: float = 60.0,
        max_retries: int = 2,
    ):
        self.api_key = api_key
        self.masked_key = mask_api_key(api_key)
        self.base_url = validate_base_url(base_url) if base_url else "https://api.anthropic.com"
        self.timeout = timeout
        self.max_retries = max(0, max_retries)

        # Initialize AsyncAnthropic with custom base URL and manual retry control
        self.client = anthropic.AsyncAnthropic(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            max_retries=0,  # We manage retries explicitly with backoff
        )

    async def complete(
        self,
        system: str,
        messages: List[Dict[str, Any]],
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str:
        """Execute a non-streaming completion request with system parameter and retries."""
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system and system.strip():
            kwargs["system"] = system.strip()

        for attempt in range(self.max_retries + 1):
            try:
                response = await self.client.messages.create(**kwargs)
                if response.content:
                    text_blocks = [
                        block.text for block in response.content if hasattr(block, "text")
                    ]
                    return "".join(text_blocks)
                return ""

            except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
                sanitized_msg = str(exc).replace(self.api_key, self.masked_key)
                logger.error(f"Anthropic authentication failed: {sanitized_msg}")
                raise LLMAuthError(f"Authentication failed: {sanitized_msg}", original_error=exc) from exc

            except anthropic.RateLimitError as exc:
                if attempt < self.max_retries:
                    delay = 1.0 * (2 ** attempt)
                    logger.warning(
                        f"Anthropic rate limit hit on model '{model}' (attempt {attempt + 1}/{self.max_retries + 1}). "
                        f"Retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                    continue
                sanitized_msg = str(exc).replace(self.api_key, self.masked_key)
                raise LLMRateLimitError(
                    f"Rate limit exceeded after {self.max_retries + 1} attempts: {sanitized_msg}",
                    original_error=exc,
                ) from exc

            except anthropic.APITimeoutError as exc:
                sanitized_msg = str(exc).replace(self.api_key, self.masked_key)
                logger.error(f"Anthropic request timed out ({self.timeout}s): {sanitized_msg}")
                raise LLMTimeoutError(
                    f"LLM request timed out after {self.timeout}s", original_error=exc
                ) from exc

            except (anthropic.InternalServerError, anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
                status_code = getattr(exc, "status_code", None)
                is_server_error = status_code is None or status_code >= 500

                if is_server_error and attempt < self.max_retries:
                    delay = 1.0 * (2 ** attempt)
                    logger.warning(
                        f"Anthropic server/connection error on model '{model}' (attempt {attempt + 1}/{self.max_retries + 1}): {exc}. "
                        f"Retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                    continue

                sanitized_msg = str(exc).replace(self.api_key, self.masked_key)
                raise LLMUnavailableError(
                    f"LLM service unavailable: {sanitized_msg}", original_error=exc
                ) from exc

            except Exception as exc:
                sanitized_msg = str(exc).replace(self.api_key, self.masked_key)
                raise LLMUnavailableError(
                    f"Unexpected error calling Anthropic provider: {sanitized_msg}",
                    original_error=exc,
                ) from exc

        raise LLMUnavailableError(f"Failed to complete request after {self.max_retries + 1} attempts.")

    async def stream(
        self,
        system: str,
        messages: List[Dict[str, Any]],
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> AsyncIterator[str]:
        """Execute a streaming completion request, yielding text delta tokens."""
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system and system.strip():
            kwargs["system"] = system.strip()

        for attempt in range(self.max_retries + 1):
            try:
                async with self.client.messages.stream(**kwargs) as stream:
                    async for text in stream.text_stream:
                        yield text
                return
            except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
                sanitized_msg = str(exc).replace(self.api_key, self.masked_key)
                raise LLMAuthError(f"Authentication failed: {sanitized_msg}", original_error=exc) from exc
            except anthropic.RateLimitError as exc:
                if attempt < self.max_retries:
                    delay = 1.0 * (2 ** attempt)
                    await asyncio.sleep(delay)
                    continue
                sanitized_msg = str(exc).replace(self.api_key, self.masked_key)
                raise LLMRateLimitError(
                    f"Rate limit exceeded during stream: {sanitized_msg}", original_error=exc
                ) from exc
            except anthropic.APITimeoutError as exc:
                raise LLMTimeoutError(f"LLM stream request timed out ({self.timeout}s)", original_error=exc) from exc
            except (anthropic.InternalServerError, anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
                status_code = getattr(exc, "status_code", None)
                if (status_code is None or status_code >= 500) and attempt < self.max_retries:
                    delay = 1.0 * (2 ** attempt)
                    await asyncio.sleep(delay)
                    continue
                sanitized_msg = str(exc).replace(self.api_key, self.masked_key)
                raise LLMUnavailableError(f"LLM stream unavailable: {sanitized_msg}", original_error=exc) from exc
            except Exception as exc:
                sanitized_msg = str(exc).replace(self.api_key, self.masked_key)
                raise LLMUnavailableError(f"Stream creation failed: {sanitized_msg}", original_error=exc) from exc

        raise LLMUnavailableError(f"Failed to initiate stream after {self.max_retries + 1} attempts.")
