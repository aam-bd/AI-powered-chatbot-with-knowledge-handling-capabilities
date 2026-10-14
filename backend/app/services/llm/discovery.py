"""LLM model auto-discovery service for Prompt 7e-2.

Fetches and normalizes model catalogs from:
- openai_models: OpenAI, Groq, DeepSeek, Ollama, vLLM
- openrouter_models: OpenRouter with pricing and context windows
- anthropic_models: Anthropic /v1/models
- gemini_native_models: Google AI Studio v1beta/models
- static: Manual model definitions

Enforces:
- Strict SSRF protection and private IP blocking
- No redirects to private addresses
- Sanitized, secret-free error messages
- No invented or hardcoded price tables
"""
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
import httpx
from urllib.parse import urlparse
from app.core.logger import logger
from app.services.llm.base import mask_api_key, validate_base_url


NON_CHAT_SUBSTRINGS = (
    "text-embedding-",
    "whisper-",
    "dall-e-",
    "tts-",
    "babbage-",
    "davinci-",
    "text-moderation-",
    "canary-",
    "realtime-",
    "audio-preview",
)


@dataclass
class DiscoveredModel:
    model_id: str
    display_name: Optional[str] = None
    context_length: Optional[int] = None
    max_output_tokens: Optional[int] = None
    price_prompt_per_1m: Optional[float] = None
    price_completion_per_1m: Optional[float] = None


class ModelDiscoveryError(Exception):
    """Sanitized model discovery exception safe for user display."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _build_models_url(base_url: str, discovery_kind: str) -> str:
    cleaned = base_url.strip().rstrip("/")
    if discovery_kind == "gemini_native_models":
        return "https://generativelanguage.googleapis.com/v1beta/models"
    
    if not cleaned.endswith("/models"):
        return f"{cleaned}/models"
    return cleaned


async def discover_models(
    base_url: str,
    api_key: Optional[str] = None,
    discovery_kind: str = "openai_models",
    timeout: float = 10.0,
) -> List[DiscoveredModel]:
    """Discover available models from an upstream LLM provider API.

    Returns a list of DiscoveredModel normalized instances.
    """
    if not base_url or not base_url.strip():
        raise ModelDiscoveryError("Base URL cannot be empty.", status_code=422)

    # SSRF verification
    try:
        validated_base = validate_base_url(base_url)
    except ValueError as exc:
        raise ModelDiscoveryError(str(exc), status_code=422)

    target_url = _build_models_url(validated_base, discovery_kind)
    headers: Dict[str, str] = {"Accept": "application/json"}

    if discovery_kind == "openrouter_models":
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
    elif discovery_kind == "anthropic_models":
        if api_key:
            headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    elif discovery_kind == "gemini_native_models":
        if api_key:
            headers["x-goog-api-key"] = api_key
    elif discovery_kind == "openai_models":
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
    elif discovery_kind == "static":
        return []

    masked_k = mask_api_key(api_key) if api_key else "None"
    logger.info(
        f"Discovering models: kind={discovery_kind}, url={target_url}, key={masked_k}"
    )

    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
            resp = await client.get(target_url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code == 401:
            raise ModelDiscoveryError(
                "Authentication failed (HTTP 401). Please check the API key.", status_code=401
            ) from exc
        elif code == 403:
            raise ModelDiscoveryError(
                "Access forbidden (HTTP 403). The provided API key does not have permission.", status_code=403
            ) from exc
        elif code == 404:
            raise ModelDiscoveryError(
                f"Endpoint not found (HTTP 404) at '{target_url}'. Please verify the base URL.", status_code=404
            ) from exc
        elif code == 429:
            raise ModelDiscoveryError(
                "Upstream rate limit exceeded (HTTP 429). Please try again shortly.", status_code=429
            ) from exc
        else:
            raise ModelDiscoveryError(
                f"Upstream provider returned HTTP {code}.", status_code=502
            ) from exc
    except httpx.TimeoutException as exc:
        raise ModelDiscoveryError(
            f"Connection timed out ({timeout}s) while querying model endpoint.", status_code=504
        ) from exc
    except httpx.RequestError as exc:
        raise ModelDiscoveryError(
            "Failed to establish network connection to the provider endpoint.", status_code=502
        ) from exc
    except Exception as exc:
        raise ModelDiscoveryError(
            "Malformed response received from model endpoint.", status_code=502
        ) from exc

    discovered: List[DiscoveredModel] = []

    # 1. OpenRouter
    if discovery_kind == "openrouter_models":
        raw_list = data.get("data", []) if isinstance(data, dict) else []
        for item in raw_list:
            if not isinstance(item, dict) or "id" not in item:
                continue
            m_id = str(item["id"])
            if any(sub in m_id.lower() for sub in NON_CHAT_SUBSTRINGS):
                continue
            # Filter non-text if modality specified
            arch = item.get("architecture")
            if isinstance(arch, dict):
                modality = str(arch.get("modality", "")).lower()
                if modality and "text" not in modality:
                    continue

            d_name = item.get("name") or m_id
            ctx_len = item.get("context_length")
            if ctx_len is not None:
                try:
                    ctx_len = int(ctx_len)
                except (ValueError, TypeError):
                    ctx_len = None

            max_out = None
            top_prov = item.get("top_provider")
            if isinstance(top_prov, dict):
                max_comp = top_prov.get("max_completion_tokens")
                if max_comp is not None:
                    try:
                        max_out = int(max_comp)
                    except (ValueError, TypeError):
                        pass

            price_prompt = None
            price_comp = None
            pricing = item.get("pricing")
            if isinstance(pricing, dict):
                try:
                    if pricing.get("prompt") is not None:
                        price_prompt = float(pricing["prompt"]) * 1_000_000
                    if pricing.get("completion") is not None:
                        price_comp = float(pricing["completion"]) * 1_000_000
                except (ValueError, TypeError):
                    pass

            discovered.append(
                DiscoveredModel(
                    model_id=m_id,
                    display_name=d_name,
                    context_length=ctx_len,
                    max_output_tokens=max_out,
                    price_prompt_per_1m=price_prompt,
                    price_completion_per_1m=price_comp,
                )
            )

    # 2. Anthropic
    elif discovery_kind == "anthropic_models":
        raw_list = data.get("data", []) if isinstance(data, dict) else []
        for item in raw_list:
            if not isinstance(item, dict) or "id" not in item:
                continue
            m_id = str(item["id"])
            d_name = item.get("display_name") or m_id
            discovered.append(DiscoveredModel(model_id=m_id, display_name=d_name))

    # 3. Google Gemini Native
    elif discovery_kind == "gemini_native_models":
        raw_list = data.get("models", []) if isinstance(data, dict) else []
        for item in raw_list:
            if not isinstance(item, dict) or "name" not in item:
                continue
            methods = item.get("supportedGenerationMethods", [])
            if "generateContent" not in methods:
                continue

            raw_name = str(item["name"])
            m_id = raw_name.replace("models/", "")
            d_name = item.get("displayName") or m_id
            ctx_len = item.get("inputTokenLimit")
            max_out = item.get("outputTokenLimit")

            discovered.append(
                DiscoveredModel(
                    model_id=m_id,
                    display_name=d_name,
                    context_length=int(ctx_len) if ctx_len is not None else None,
                    max_output_tokens=int(max_out) if max_out is not None else None,
                )
            )

    # 4. OpenAI & Standard OpenAI Compat (Groq, DeepSeek, Ollama)
    else:
        raw_list = data.get("data", []) if isinstance(data, dict) else []
        for item in raw_list:
            if not isinstance(item, dict) or "id" not in item:
                continue
            m_id = str(item["id"])
            # Filter obvious non-chat models
            if any(sub in m_id.lower() for sub in NON_CHAT_SUBSTRINGS):
                continue

            ctx_len = item.get("context_window")  # Provided by Groq
            if ctx_len is not None:
                try:
                    ctx_len = int(ctx_len)
                except (ValueError, TypeError):
                    ctx_len = None

            discovered.append(
                DiscoveredModel(
                    model_id=m_id,
                    display_name=m_id,
                    context_length=ctx_len,
                )
            )

    logger.info(f"Discovered {len(discovered)} models from {target_url}")
    return discovered
