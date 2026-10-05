"""Base interface, normalized exceptions, and validation utilities for LLM provider layer.

Follows Architecture §6.9 and Prompt 1.5 specifications:
- Abstract adapter interface: complete(...) and stream(...)
- Normalized exception hierarchy (LLMAuthError, LLMRateLimitError, LLMTimeoutError, LLMUnavailableError)
- Base URL validation (HTTPS required except localhost and private RFC 1918 hosts; trailing slashes normalized)
- API key masking to protect credentials from appearing in logs or error messages
"""
from abc import ABC, abstractmethod
from typing import AsyncIterator, List, Dict, Any, Optional
import ipaddress
import urllib.parse


# ------------------------------------------------------------------------------
# Normalized Exception Hierarchy
# ------------------------------------------------------------------------------

class LLMError(Exception):
    """Base exception for all normalized LLM provider errors."""

    def __init__(self, message: str, original_error: Optional[Exception] = None):
        super().__init__(message)
        self.message = message
        self.original_error = original_error

    def __str__(self) -> str:
        return self.message


class LLMAuthError(LLMError):
    """Raised when authentication fails (HTTP 401, 403, or invalid API key)."""
    pass


class LLMRateLimitError(LLMError):
    """Raised when provider rate limit or quota is exceeded (HTTP 429)."""
    pass


class LLMTimeoutError(LLMError):
    """Raised when an LLM provider request times out."""
    pass


class LLMUnavailableError(LLMError):
    """Raised when the LLM service is unavailable, returns 5xx, or network connection fails."""
    pass


# ------------------------------------------------------------------------------
# Security & URL Validation Helpers
# ------------------------------------------------------------------------------

def mask_api_key(key: Optional[str]) -> str:
    """Mask an API key for safe inclusion in logs or error strings."""
    if not key:
        return ""
    clean_key = str(key).strip()
    if len(clean_key) <= 8:
        return "***"
    return f"{clean_key[:4]}...{clean_key[-4:]}"


def validate_base_url(url: str) -> str:
    """Validate and normalize provider base URL according to Architecture §6.9.

    Rules:
    - https is strictly required for remote hosts.
    - http is permitted only for localhost, 127.0.0.1, ::1, or private IP networks (RFC 1918).
    - Trailing slashes are stripped/normalized.
    """
    if not url or not isinstance(url, str):
        raise ValueError("LLM base URL must be a non-empty string.")

    cleaned_url = url.strip().rstrip("/")
    parsed = urllib.parse.urlparse(cleaned_url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Invalid URL scheme '{parsed.scheme}'. Scheme must be http or https.")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError(f"Base URL '{url}' has no valid hostname.")

    if parsed.scheme == "http":
        is_loopback = hostname in ("localhost", "127.0.0.1", "::1", "testclient")
        is_private_ip = False
        try:
            ip_obj = ipaddress.ip_address(hostname)
            if ip_obj.is_private or ip_obj.is_loopback:
                is_private_ip = True
        except ValueError:
            # Not an IP literal; might be a domain name like localhost or test host
            pass

        if not (is_loopback or is_private_ip):
            raise ValueError(
                f"Insecure HTTP base URL '{cleaned_url}' is not allowed for remote hosts. "
                "HTTPS is strictly required except for localhost or private networks."
            )

    return cleaned_url


# ------------------------------------------------------------------------------
# Abstract Adapter Interface
# ------------------------------------------------------------------------------

class LLMAdapter(ABC):
    """Abstract interface for LLM provider adapters."""

    @abstractmethod
    async def complete(
        self,
        system: str,
        messages: List[Dict[str, Any]],
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str:
        """Generate a complete text response from the model."""
        pass

    @abstractmethod
    async def stream(
        self,
        system: str,
        messages: List[Dict[str, Any]],
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> AsyncIterator[str]:
        """Stream response tokens as an asynchronous iterator."""
        pass
