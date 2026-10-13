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


def validate_base_url(url: str, allow_private: Optional[bool] = None) -> str:
    """Validate and normalize provider base URL according to Architecture §6.9 and Prompt 7e.

    Rules:
    - https is strictly required in production.
    - If allow_private is False (default in config): block private, loopback, link-local,
      and reserved ranges after DNS resolution (SSRF defense).
    - If allow_private is True: http is permitted only for localhost or RFC 1918 private IPs
      in non-production environments (e.g. for local Ollama in dev).
    - Insecure remote HTTP is strictly forbidden.
    - Trailing slashes are stripped/normalized.
    """
    if not url or not isinstance(url, str):
        raise ValueError("LLM base URL must be a non-empty string.")

    from app.core.config import settings
    from app.services.parsers.web import is_forbidden_ip

    cleaned_url = url.strip().rstrip("/")
    parsed = urllib.parse.urlparse(cleaned_url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Invalid URL scheme '{parsed.scheme}'. Scheme must be http or https.")

    hostname = (parsed.hostname or "").lower().strip()
    if not hostname:
        raise ValueError(f"Base URL '{url}' has no valid hostname.")

    is_prod = settings.APP_ENV == "production"
    if is_prod and parsed.scheme != "https":
        raise ValueError("HTTPS is strictly required for LLM base URLs in production.")

    effective_allow_private = (
        allow_private if allow_private is not None else settings.ALLOW_PRIVATE_LLM_URLS
    )

    if not effective_allow_private:
        # SSRF Protection: Reject private, loopback, and link-local addresses
        if is_forbidden_ip(hostname):
            raise ValueError(
                f"SSRF Protection: Access to Private, loopback, or reserved IP '{hostname}' is forbidden for LLM base URL."
            )
        try:
            import socket
            addr_info = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
            resolved_ips = {item[4][0] for item in addr_info}
            for ip_str in resolved_ips:
                if is_forbidden_ip(ip_str):
                    raise ValueError(
                        f"SSRF Protection: Hostname '{hostname}' resolves to private or forbidden IP '{ip_str}'."
                    )
        except ValueError:
            raise
        except Exception as exc:
            if is_prod:
                raise ValueError(
                    f"SSRF Protection: DNS resolution failed for hostname '{hostname}': {exc}"
                ) from exc

    if parsed.scheme == "http":
        is_loopback = hostname in ("localhost", "127.0.0.1", "::1", "testclient")
        is_private_ip = False
        try:
            ip_obj = ipaddress.ip_address(hostname)
            if ip_obj.is_private or ip_obj.is_loopback:
                is_private_ip = True
        except ValueError:
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
