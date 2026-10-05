"""OpenAI-compatible LLM adapter.

Covers OpenAI, OpenRouter, Google Gemini (OpenAI-compatible endpoint), Ollama, vLLM, and any compliant endpoint.
Implements:
- System prompt prepended to messages as {"role": "system", "content": ...}
- Exponential backoff retries on HTTP 429 and 5xx (up to LLM_MAX_RETRIES)
- Error mapping to normalized LLM exceptions
- Token streaming via AsyncIterator[str]
- Strict credential masking in logs and error messages
"""
import asyncio
from typing import AsyncIterator, List, Dict, Any, Optional
import openai
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


class OpenAICompatAdapter(LLMAdapter):
    """Adapter for OpenAI-compatible Chat Completions API."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout: float = 60.0,
        max_retries: int = 2,
    ):
        self.api_key = api_key
        self.masked_key = mask_api_key(api_key)
        self.base_url = validate_base_url(base_url)
        self.timeout = timeout
        self.max_retries = max(0, max_retries)

        # Initialize AsyncOpenAI with custom base URL and manual retry control
        self.client = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout,
            max_retries=0,  # We manage retries explicitly with backoff
        )

    def _prepare_messages(
        self, system: Optional[str], messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Prepend system prompt as {"role": "system", "content": system}."""
        prepared: List[Dict[str, Any]] = []
        if system and system.strip():
            prepared.append({"role": "system", "content": system.strip()})
        prepared.extend(messages)
        return prepared

    async def complete(
        self,
        system: str,
        messages: List[Dict[str, Any]],
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str:
        """Execute a non-streaming completion request with retries and error normalization."""
        full_messages = self._prepare_messages(system, messages)

        for attempt in range(self.max_retries + 1):
            try:
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=full_messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                if response.choices and response.choices[0].message:
                    return response.choices[0].message.content or ""
                return ""

            except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
                sanitized_msg = str(exc).replace(self.api_key, self.masked_key)
                logger.error(f"OpenAICompat authentication failed: {sanitized_msg}")
                raise LLMAuthError(f"Authentication failed: {sanitized_msg}", original_error=exc) from exc

            except openai.RateLimitError as exc:
                if attempt < self.max_retries:
                    delay = 1.0 * (2 ** attempt)
                    logger.warning(
                        f"OpenAICompat rate limit hit on model '{model}' (attempt {attempt + 1}/{self.max_retries + 1}). "
                        f"Retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                    continue
                sanitized_msg = str(exc).replace(self.api_key, self.masked_key)
                raise LLMRateLimitError(
                    f"Rate limit exceeded after {self.max_retries + 1} attempts: {sanitized_msg}",
                    original_error=exc,
                ) from exc

            except openai.APITimeoutError as exc:
                sanitized_msg = str(exc).replace(self.api_key, self.masked_key)
                logger.error(f"OpenAICompat request timed out ({self.timeout}s): {sanitized_msg}")
                raise LLMTimeoutError(
                    f"LLM request timed out after {self.timeout}s", original_error=exc
                ) from exc

            except (openai.InternalServerError, openai.APIConnectionError, openai.APIStatusError) as exc:
                status_code = getattr(exc, "status_code", None)
                is_server_error = status_code is None or status_code >= 500

                if is_server_error and attempt < self.max_retries:
                    delay = 1.0 * (2 ** attempt)
                    logger.warning(
                        f"OpenAICompat server/connection error on model '{model}' (attempt {attempt + 1}/{self.max_retries + 1}): {exc}. "
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
                    f"Unexpected error calling OpenAI-compatible provider: {sanitized_msg}",
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
        full_messages = self._prepare_messages(system, messages)

        stream_response = None
        for attempt in range(self.max_retries + 1):
            try:
                stream_response = await self.client.chat.completions.create(
                    model=model,
                    messages=full_messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stream=True,
                )
                break
            except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
                sanitized_msg = str(exc).replace(self.api_key, self.masked_key)
                raise LLMAuthError(f"Authentication failed: {sanitized_msg}", original_error=exc) from exc
            except openai.RateLimitError as exc:
                if attempt < self.max_retries:
                    delay = 1.0 * (2 ** attempt)
                    await asyncio.sleep(delay)
                    continue
                sanitized_msg = str(exc).replace(self.api_key, self.masked_key)
                raise LLMRateLimitError(
                    f"Rate limit exceeded during stream: {sanitized_msg}", original_error=exc
                ) from exc
            except openai.APITimeoutError as exc:
                raise LLMTimeoutError(f"LLM stream request timed out ({self.timeout}s)", original_error=exc) from exc
            except (openai.InternalServerError, openai.APIConnectionError, openai.APIStatusError) as exc:
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

        if not stream_response:
            raise LLMUnavailableError("Failed to initiate stream.")

        try:
            async for chunk in stream_response:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as exc:
            sanitized_msg = str(exc).replace(self.api_key, self.masked_key)
            logger.error(f"Error during stream consumption: {sanitized_msg}")
            raise LLMUnavailableError(f"Error during streaming: {sanitized_msg}", original_error=exc) from exc
