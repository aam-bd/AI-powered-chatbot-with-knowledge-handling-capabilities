"""LLM provider factory for role-based adapter construction.

Builds an LLMAdapter per role ('router' and 'answer') from FAST_LLM_* and ANSWER_LLM_* overrides,
falling back to shared LLM_* settings, as specified in Architecture §6.9 and §12.
"""
from typing import Tuple
from app.core.config import settings
from app.services.llm.base import LLMAdapter
from app.services.llm.openai_compat import OpenAICompatAdapter
from app.services.llm.anthropic import AnthropicAdapter


def get_llm_adapter(role: str) -> Tuple[LLMAdapter, str]:
    """Construct and return the appropriate LLM adapter and model name for the given role.

    Args:
        role: Either "router" (for fast query intent routing & rewriting)
              or "answer" (for grounded response generation).

    Returns:
        Tuple of (LLMAdapter instance, configured model name).

    Raises:
        ValueError: If role is unrecognized, or if required credentials/models are missing.
    """
    normalized_role = role.lower().strip()
    if normalized_role not in ("router", "answer"):
        raise ValueError(f"Unknown LLM role '{role}'. Valid roles are 'router' and 'answer'.")

    timeout = float(settings.LLM_TIMEOUT_SECONDS)
    max_retries = int(settings.LLM_MAX_RETRIES)

    if normalized_role == "router":
        provider = (settings.FAST_LLM_PROVIDER or settings.LLM_PROVIDER).lower().strip()
        base_url = settings.FAST_LLM_BASE_URL or settings.LLM_BASE_URL
        api_key_secret = settings.FAST_LLM_API_KEY or settings.LLM_API_KEY
        model = settings.FAST_MODEL
        key_env_var = "FAST_LLM_API_KEY or LLM_API_KEY"
        model_env_var = "FAST_MODEL"
    else:  # "answer"
        provider = (settings.ANSWER_LLM_PROVIDER or settings.LLM_PROVIDER).lower().strip()
        base_url = settings.ANSWER_LLM_BASE_URL or settings.LLM_BASE_URL
        api_key_secret = settings.ANSWER_LLM_API_KEY or settings.LLM_API_KEY
        model = settings.ANSWER_MODEL
        key_env_var = "ANSWER_LLM_API_KEY or LLM_API_KEY"
        model_env_var = "ANSWER_MODEL"

    if not api_key_secret or not api_key_secret.get_secret_value():
        raise ValueError(f"LLM API key is not configured for role '{role}'. Set {key_env_var} in .env.")

    if not model or not model.strip():
        raise ValueError(f"LLM model name is not configured for role '{role}'. Set {model_env_var} in .env.")

    api_key = api_key_secret.get_secret_value()

    if provider == "openai_compatible":
        adapter = OpenAICompatAdapter(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )
    elif provider == "anthropic":
        adapter = AnthropicAdapter(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )
    else:
        raise ValueError(
            f"Unsupported LLM provider '{provider}' for role '{role}'. "
            "Supported providers are 'openai_compatible' and 'anthropic'."
        )

    return adapter, model.strip()
